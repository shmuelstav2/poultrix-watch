// ==UserScript==
// @name         Poultrix method probe
// @namespace    poultrix.probe
// @version      1.0
// @description  Runs in the logged-in Poultrix app and tests which extraction / farm-switch methods work; POSTs a report to the local collector (domain=selftest).
// @match        https://app.poultrix.com/*
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @updateURL    https://raw.githubusercontent.com/shmuelstav2/poultrix-watch/main/poultrix_probe.user.js
// @downloadURL  https://raw.githubusercontent.com/shmuelstav2/poultrix-watch/main/poultrix_probe.user.js
// ==/UserScript==
(function () {
  'use strict';
  const COLLECTOR = 'http://127.0.0.1:8765/save';
  const log = (...a) => console.log('[PoultrixProbe]', ...a);

  if (/login\.aspx/i.test(location.pathname)) { log('on login page - not logged in yet'); return; }

  const post = (obj) => GM_xmlhttpRequest({
    method: 'POST', url: COLLECTOR,
    headers: { 'Content-Type': 'application/json' },
    data: JSON.stringify(obj),
    onload: r => log('posted', r.status), onerror: e => log('post err', e),
  });

  const getVal = (o) => { try { return o && o.GetValue ? o.GetValue() : null; } catch (e) { return null; } };

  async function fetchText(url) {
    try { const r = await fetch(url, { credentials: 'include' });
      return { ok: r.ok, status: r.status, len: (await r.text()).length }; }
    catch (e) { return { ok: false, err: String(e) }; }
  }
  async function fetchJson(url) {
    try { const r = await fetch(url, { credentials: 'include' });
      const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (_) {}
      return { ok: r.ok, status: r.status, len: t.length, isJson: !!j,
               count: Array.isArray(j) ? j.length : (j ? Object.keys(j).length : 0) }; }
    catch (e) { return { ok: false, err: String(e) }; }
  }

  async function run() {
    const report = { url: location.href, title: document.title, ts: new Date().toISOString(),
                     currentFarm: getVal(window.lstFarms), currentFlock: getVal(window.cbMidgar),
                     tests: {} };

    // METHOD A: report pages (the proven extraction source)
    report.tests.report7 = await fetchText('/Report7.aspx?Grow=BroilerDashboard');
    report.tests.report9 = await fetchText('/Report9.aspx?Grow=BroilerDashboard');

    // METHOD B: internal JSON API
    const farm = report.currentFarm || '';
    report.tests.getMidgarim = await fetchJson('/ws/GeneralHandler.ashx?action=GetMidgarimForFarm&farmId=' + encodeURIComponent(farm));
    report.tests.getHenHouses = await fetchJson('/ws/GeneralHandler.ashx?action=GetHenHousesForFarm&farmId=' + encodeURIComponent(farm));

    // farm list (for switching)
    let farmList = [];
    try {
      if (window.lstFarms && window.lstFarms.GetItemCount) {
        for (let i = 0; i < window.lstFarms.GetItemCount(); i++) {
          const it = window.lstFarms.GetItem(i);
          farmList.push({ v: it && it.value, t: it && it.text });
        }
      }
    } catch (e) { report.farmListErr = String(e); }
    report.farmCount = farmList.length;
    report.farmSample = farmList.slice(0, 5);

    // METHOD C: try switching farm via the combo API (report if it changes / freezes)
    if (farmList.length > 1) {
      const before = getVal(window.lstFarms);
      const target = farmList.find(f => String(f.v) !== String(before));
      report.switchTarget = target;
      try {
        const t0 = Date.now();
        window.lstFarms.SetValue(target.v);
        if (window.lstFarms.PerformCallback) window.lstFarms.PerformCallback('farmChanged');
        await new Promise(r => setTimeout(r, 4000));
        report.tests.switchCombo = { before, after: getVal(window.lstFarms),
                                     changed: String(getVal(window.lstFarms)) === String(target.v),
                                     ms: Date.now() - t0 };
      } catch (e) { report.tests.switchCombo = { err: String(e) }; }
    }

    log('report', report);
    post({ domain: 'selftest', farm: report.currentFarm, farmId: report.currentFarm,
           flock: report.currentFlock, rows: [report] });
  }

  setTimeout(run, 4000);
})();
