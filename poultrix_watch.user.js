// ==UserScript==
// @name         Poultrix Kfar Harif hourly watcher
// @namespace    poultrix.kfarharif
// @version      0.2
// @description  Hourly scrape of Kfar Harif daily data (mortality / weighings / feed); saves changes to a local file via the collector. Keep-alive prevents session timeout.
// @match        https://app.poultrix.com/DailyFollowUpV1.aspx*
// @match        https://app.poultrix.com/SessionTimeOut.aspx*
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==
(function () {
  'use strict';

  // ---- config ----------------------------------------------------------
  const FARM_ID   = '482';               // כפר הריף
  const FARM_NAME = 'כפר הריף';
  const COLLECTOR = 'http://127.0.0.1:8765/save';
  const SCRAPE_INTERVAL_MS   = 60 * 60 * 1000;   // hourly scrape
  const KEEPALIVE_INTERVAL_MS = 5 * 60 * 1000;   // ping every 5 min -> session never times out
  const RUN_MIN_GAP_MS = 50 * 60 * 1000;         // don't re-scrape within 50 min (survives reloads)

  const log = (...a) => console.log('[PoultrixWatch]', ...a);
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // If we landed on the session-timeout page, bounce back to the app (session usually restores).
  if (location.pathname.toLowerCase().includes('sessiontimeout')) {
    log('session timed out -> reloading app');
    location.href = 'https://app.poultrix.com/DailyFollowUpV1.aspx?Grow=BroilerDashboard';
    return;
  }

  // ---- keep-alive: hitting an ashx endpoint resets the ASP.NET session timer ----
  function keepAlive() {
    fetch('/ws/GeneralHandler.ashx?action=GetFoodConsumptionForDay&midgarText=' +
          encodeURIComponent(currentFlock() || '') + '&farmId=' + FARM_ID,
          { credentials: 'include' })
      .then(() => log('keep-alive ok'))
      .catch(e => log('keep-alive failed', e));
  }

  function currentFlock() {
    try { return window.cbMidgar && window.cbMidgar.GetValue ? window.cbMidgar.GetValue() : ''; }
    catch (e) { return ''; }
  }

  function currentFarm() {
    try { return window.lstFarms && window.lstFarms.GetValue ? String(window.lstFarms.GetValue()) : ''; }
    catch (e) { return ''; }
  }

  function clickRefresh() {
    const el = [...document.querySelectorAll('*')]
      .find(n => n.children.length === 0 && (n.textContent || '').trim() === 'רענן נתונים');
    if (el) { el.click(); return true; }
    return false;
  }

  // ---- scraper: reads the daily grid using the known column layout -------
  const COL = { building: 2, age: 3, population: 4, balance: 5, mortality: 6, culls: 7,
                weight: 8, water: 9, feed: 10, ph: 11, totalMort: 12, mortPct: 13,
                cumMort: 14, cumMortPct: 15, stdWeight: 16, weightPct: 17,
                waterPerK: 18, feedPerK: 19, waterFeed: 20, notes: 21 };
  const NCOLS = 22;

  function scrapeDaily() {
    const allTr = [...document.querySelectorAll('tr')];
    const rows = [];
    let curDate = '';
    for (const tr of allTr) {
      const txt = (tr.innerText || '').trim();
      const dm = txt.match(/תאריך:?\s*([0-9]{1,2}\/[0-9]{1,2}\/[0-9]{2,4})/);
      if (dm) { curDate = dm[1]; continue; }
      if (tr.children.length !== NCOLS) continue;
      const c = [...tr.children].map(td => (td.innerText || '').trim());
      const building = c[COL.building];
      if (!building || /מבנ|אכלוס/.test(building)) continue; // skip header + per-date totals
      rows.push({
        date: curDate, building,
        age: c[COL.age], population: c[COL.population], balance: c[COL.balance],
        mortality: c[COL.mortality], culls: c[COL.culls], weight: c[COL.weight],
        water: c[COL.water], feed: c[COL.feed], totalMort: c[COL.totalMort],
        cumMort: c[COL.cumMort], stdWeight: c[COL.stdWeight], notes: c[COL.notes],
      });
    }
    return rows;
  }

  function sig(r) {
    return [r.mortality, r.culls, r.weight, r.feed, r.population, r.notes].join('|');
  }

  function diff(rows) {
    const seen = GM_getValue('seen', {});
    const now = {};
    const changes = [];
    for (const r of rows) {
      const key = r.date + '|' + r.building;
      now[key] = sig(r);
      if (seen[key] === undefined) changes.push({ type: 'new', ...r });
      else if (seen[key] !== now[key]) changes.push({ type: 'changed', ...r });
    }
    GM_setValue('seen', now);
    return changes;
  }

  function post(payload) {
    GM_xmlhttpRequest({
      method: 'POST', url: COLLECTOR,
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify(payload),
      onload: r => log('collector:', r.status, r.responseText),
      onerror: e => log('collector error', e),
    });
  }

  async function runOnce() {
    const last = GM_getValue('last_run', 0);
    if (Date.now() - last < RUN_MIN_GAP_MS) { log('skip; ran recently'); return; }

    const farm = currentFarm();
    if (farm && farm !== FARM_ID) {
      // not on Kfar Harif (e.g. after a reload) — record it so it can be re-selected
      post({ timestamp: new Date().toISOString(), changes: [], rows: [],
             note: 'tab is on farm ' + farm + ', not ' + FARM_NAME + ' (' + FARM_ID + '). Select Kfar Harif.' });
      return;
    }

    GM_setValue('last_run', Date.now());
    clickRefresh();
    await sleep(7000); // wait for grid render

    const rows = scrapeDaily();
    log('scraped rows:', rows.length);
    const changes = diff(rows);
    log('changes:', changes.length);
    post({ timestamp: new Date().toISOString(), farm: FARM_NAME, flock: currentFlock(),
           rowCount: rows.length, changes, rows });
  }

  // ---- schedule --------------------------------------------------------
  window.addEventListener('load', () => {
    setTimeout(keepAlive, 10000);
    setTimeout(runOnce, 12000);
    setInterval(keepAlive, KEEPALIVE_INTERVAL_MS);
    setInterval(runOnce, SCRAPE_INTERVAL_MS);
  });
})();
