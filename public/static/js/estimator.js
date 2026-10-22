/* =====================================================================
   Vehicle Registration Excise Estimator
   - Part 1: calculation engine (pure functions, no DOM; testable in Node)
   - Part 2: UI glue (runs only in the browser)
   ===================================================================== */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------- helpers

  // Parse "YYYY-MM-DD" as a LOCAL date. (new Date("2026-07-01") is UTC midnight,
  // which shifts to 30 June in time zones west of UTC and breaks fiscal-year logic.)
  function parseDate(str) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(str || '');
    if (!m) return null;
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    return isNaN(d.getTime()) ? null : d;
  }

  // Fiscal year START year: Jan 2026 -> 2025 (FY 2025-26), Aug 2026 -> 2026 (FY 2026-27)
  function fiscalYear(d) {
    return d.getMonth() + 1 >= 7 ? d.getFullYear() : d.getFullYear() - 1;
  }

  function fyLabel(fy) {
    return fy + '-' + String((fy + 1) % 100).padStart(2, '0');
  }

  // Whole days between two local dates, immune to daylight-saving shifts
  function daysBetween(a, b) {
    const ua = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate());
    const ub = Date.UTC(b.getFullYear(), b.getMonth(), b.getDate());
    return Math.round((ub - ua) / 86400000);
  }

  // Completed calendar years between two dates (anniversary based), never negative
  function completedYears(from, to) {
    let y = to.getFullYear() - from.getFullYear();
    const md = to.getMonth() - from.getMonth();
    if (md < 0 || (md === 0 && to.getDate() < from.getDate())) y -= 1;
    return Math.max(0, y);
  }

  // FY quarters: Q1 Jul-Sep, Q2 Oct-Dec, Q3 Jan-Mar, Q4 Apr-Jun
  function quarterFractionRemaining(d) {
    const m = d.getMonth() + 1;
    if (m >= 7 && m <= 9) return 1;
    if (m >= 10 && m <= 12) return 0.75;
    if (m >= 1 && m <= 3) return 0.5;
    return 0.25;
  }

  const num = (v) => {
    const n = parseFloat(v);
    return isFinite(n) && n > 0 ? n : 0; // negatives / blanks treated as 0
  };

  const isTransferCase = (txn) => txn === 'nrt' || txn === 'transfer';

  // ---------------------------------------------------------------- rate tables

  // Motor Vehicle Tax annual rate (value based: Motor Car / EV over 1000cc)
  // FY 2026-27 rates apply from 2026 onward (previously only to exactly 2026,
  // so FY 2027-28+ silently fell back to the older rates).
  function mvtRateForFY(fy, cc) {
    if (fy >= 2026) {
      if (cc > 2000) return 0.004;
      if (cc >= 1001) return 0.003;
      return 0;
    }
    if (cc > 2000) return 0.003;
    if (cc >= 1001) return 0.002;
    return 0;
  }

  // Commercial MVT (laden-weight based, flat annual amount)
  function mvtWeightAmount(fy, w) {
    if (fy >= 2026) {
      if (w <= 4060) return 1000;
      if (w <= 8120) return 6600;
      if (w <= 12000) return 12000;
      if (w <= 16000) return 18000;
      return 24000;
    }
    if (w <= 4060) return 1000;
    if (w <= 8120) return 2200;
    if (w <= 12000) return 4000;
    if (w <= 16000) return 6000;
    return 8000;
  }

  function incomeTaxCarBase(cc, filer) {
    let f;
    if (cc <= 1000) f = 10000;
    else if (cc <= 1199) f = 1500;
    else if (cc <= 1299) f = 1750;
    else if (cc <= 1499) f = 2500;
    else if (cc <= 1599) f = 3750;
    else if (cc <= 1999) f = 4500;
    else f = 10000;
    return filer ? f : f * 3;
  }

  function whtRate(cc, filer) {
    if (cc > 2000) return filer ? 50000 : 150000;
    if (cc > 1800) return filer ? 18750 : 37500;
    if (cc > 1000) return filer ? 12500 : 25000;
    if (cc >= 851) return filer ? 5000 : 15000;
    return 0;
  }

  // ---------------------------------------------------------------- line items

  function registrationFee(txn, v, totalValue, cc) {
    if (txn === 'transfer') return 0;
    if (v === 'motorcycle' || v === 'commercial') return totalValue * 0.01;
    const rate = cc <= 1000 ? 0.01 : cc <= 2000 ? 0.02 : 0.04;
    if (v === 'car') return totalValue * rate;
    if (v === 'ev') return totalValue * rate * 0.05; // 95% concession
    return 0;
  }

  // Lifetime token applies to motorcycles and cars up to 1000cc; everything else pays MVT.
  // (Was "cc <= 999", which left an exactly-1000cc car paying neither token nor MVT.)
  function tokenBase(v, motorCycleSub, cc, filer) {
    if (v === 'motorcycle') return motorCycleSub === 'rickshaw' ? 3000 : 1500;
    if (v === 'car' && cc <= 1000) return filer ? 20000 : 40000;
    return 0;
  }

  function lifetimeTokenTax(txn, base, yearsElapsed) {
    if (!base) return 0;
    if (txn === 'transfer') return yearsElapsed > 10 ? 0 : base * Math.pow(0.9, yearsElapsed);
    return base;
  }

  function mvtSplit(v, ladenWeight, totalValue, cc, invDate, regDate) {
    const fyI = fiscalYear(invDate), fyR = fiscalYear(regDate);
    const annual = (fy) => (v === 'commercial' ? mvtWeightAmount(fy, ladenWeight) : totalValue * mvtRateForFY(fy, cc));

    if (fyI >= fyR) {
      // Same fiscal year: only the remaining quarters of that year, no arrears
      return { current: annual(fyR) * quarterFractionRemaining(invDate), arrears: 0 };
    }
    // Different years: registration FY in full; invoice FY partial + any full years between = arrears
    let arrears = annual(fyI) * quarterFractionRemaining(invDate);
    for (let y = fyI + 1; y < fyR; y++) arrears += annual(y);
    return { current: annual(fyR), arrears };
  }

  function incomeTax(txn, v, ladenWeight, yearsMultiplier, filer, cc) {
    if (txn === 'transfer') return 0;
    if (v === 'commercial') return ladenWeight * (filer ? 2.5 : 5) * yearsMultiplier;
    if (v === 'car' || v === 'ev') return incomeTaxCarBase(cc, filer) * yearsMultiplier;
    return 0;
  }

  function hpaFee(selected, v, cc) {
    if (!selected) return 0;
    if (v === 'motorcycle') return 150;
    if (v === 'commercial') return 9075;
    if (cc <= 1000) return 1200;
    if (cc <= 1800) return 1975;
    return 18150;
  }

  function professionalTax(txn, v, yearsMultiplier) {
    if (v === 'motorcycle' && txn === 'transfer') return 0;
    return 200 * yearsMultiplier;
  }

  function additionalMarkFee(v, cc, commercialSub) {
    if (v === 'motorcycle') return 1000;
    if (v === 'commercial') return commercialSub === 'htv' ? 5000 : 1000;
    if (cc <= 1000) return 2000;
    if (cc <= 1800) return 4000;
    return 6000;
  }

  function lateRegistrationFee(txn, days, v, commercialSub) {
    if (txn === 'transfer' || days <= 0) return 0;
    if (v === 'motorcycle') return days > 30 ? 500 : 0;
    if (v === 'commercial' && commercialSub === 'tractor') {
      if (days > 240) return 10000;
      if (days > 180) return 8000;
      if (days > 60) return 5000;
      return 0;
    }
    if (days > 150) return 15000;
    if (days > 120) return 10000;
    if (days > 90) return 7000;
    if (days > 60) return 5000;
    if (days > 30) return 3000;
    return 0;
  }

  function rebate(regDate, currentMVT) {
    if (!currentMVT) return 0;
    const m = regDate.getMonth() + 1;
    return m === 7 || m === 8 ? -0.1 * currentMVT : 0;
  }

  function capitalValueTax(txn, selected, cc, invDate, regDate, totalValue) {
    if (cc < 1300) return 0;
    let cvt = selected ? totalValue * 0.01 : 0;
    if (txn === 'nrt') {
      cvt += totalValue * 0.01;
    } else if (txn === 'transfer') {
      const yrs = completedYears(invDate, regDate); // clamped: no negative years
      if (yrs <= 5) cvt += (totalValue * 0.01 / 5) * (5 - yrs);
    }
    return cvt;
  }

  // Previously referenced an undefined variable (commercialSub) and crashed for Commercial vehicles
  function transferFee(txn, v, cc, commercialSub) {
    if (!isTransferCase(txn)) return 0;
    if (v === 'motorcycle') return 910;
    if (v === 'commercial' && commercialSub === 'htv') return 9075;
    if (cc > 1800) return 18150;
    if (cc > 1000) return 9075;
    return 4540;
  }

  function withholdingTax(txn, v, cc, yearsElapsed, filer) {
    if (txn === 'new' || v === 'commercial') return 0;
    let wht = whtRate(cc, filer);
    if (txn === 'nrt') return wht;
    if (yearsElapsed > 1 && yearsElapsed <= 5) wht *= Math.pow(0.9, yearsElapsed);
    else if (yearsElapsed > 5) wht *= Math.pow(0.9, 5);
    return wht;
  }

  function advanceWHT(txn, cc, filer) {
    if (txn !== 'nrt') return 0;
    if (cc > 2000) return filer ? 300000 : 900000;
    if (cc > 1000) return filer ? 200000 : 600000;
    if (cc >= 851) return filer ? 100000 : 300000;
    return 0;
  }

  // Transfer lifetime token: only for vehicles that pay lifetime token at all.
  // (Previously ANY vehicle with cc <= 1000 got Rs 20,000 — e.g. every Commercial
  // vehicle, since their CC was usually left at 0.)
  function transferLTT(txn, v, motorCycleSub, cc, invDate, regDate) {
    let base = 0;
    if (v === 'motorcycle') base = motorCycleSub === 'rickshaw' ? 3000 : 1500;
    else if (v === 'car' && cc <= 1000) base = 20000;
    if (!base) return 0;
    if (txn === 'nrt') return base;
    if (txn === 'transfer') {
      const yrs = Math.max(0, fiscalYear(regDate) - fiscalYear(invDate));
      if (yrs >= 10) return 0;
      return base * (1 - yrs * 0.1);
    }
    return 0;
  }

  // ---------------------------------------------------------------- main

  const LABELS = {
    registrationFee: 'Registration fee',
    mvt: 'Motor vehicle tax (current year)',
    mvtArrears: 'Motor vehicle tax (arrears)',
    incomeTax: 'Income tax',
    lifetimeToken: 'Lifetime token tax',
    hpa: 'HPA (hire purchase agreement)',
    cardFee: 'Automated registration card fee',
    professionalTax: 'Professional tax',
    lateFee: 'Late registration fee',
    markFee: 'Additional registration mark fee',
    platform: 'Govt. platform charges',
    cvt: 'Capital value tax (CVT)',
    rebate: 'Rebate (July–August, 10% of MVT)',
    transferFee: 'Transfer fee',
    wht: 'Withholding tax',
    advanceWht: 'Advance withholding tax',
    transferLtt: 'Transfer lifetime token tax'
  };

  function compute(raw) {
    const txn = raw.txn;
    const v = raw.vehicle;
    const filer = raw.filer !== false;
    const warnings = [];

    const invoiceValue = num(raw.invoiceValue);
    const advanceTax = num(raw.advanceTax);
    const totalValue = invoiceValue + advanceTax;
    const ladenWeight = num(raw.ladenWeight);
    const kw = num(raw.kw);
    const cc = v === 'ev' ? kw * 18.77 : num(raw.cc);

    const invDate = parseDate(raw.invoiceDate);
    const regDate = parseDate(raw.regDate);

    if (!invDate || !regDate) {
      return { ok: false, warnings: ['Enter both dates to see the estimate.'], lines: [], total: 0, meta: { totalValue, cc } };
    }

    let days = daysBetween(invDate, regDate);
    if (days < 0) {
      warnings.push(txn === 'transfer'
        ? 'The transfer date is before the original registration date. Check both dates.'
        : 'The registration date is before the invoice date. Check both dates.');
    }
    if (invoiceValue === 0) warnings.push('Invoice value is 0, so value-based taxes show as 0.');
    if (v === 'ev' && kw === 0) warnings.push('Enter the kW rating; CC-based slabs are worked out from it.');
    if ((v === 'car' || v === 'commercial') && cc === 0) warnings.push('Engine CC is 0, so CC-based slabs use the lowest band.');
    if (v === 'commercial' && ladenWeight === 0) warnings.push('Enter the laden weight; commercial MVT and income tax depend on it.');

    const fyI = fiscalYear(invDate), fyR = fiscalYear(regDate);
    const yearsElapsed = Math.max(0, fyR - fyI);
    const yearsMultiplier = yearsElapsed + 1;

    const base = tokenBase(v, raw.motorCycleSub, cc, filer);
    const usesMVT = base === 0;
    const mvt = usesMVT ? mvtSplit(v, ladenWeight, totalValue, cc, invDate, regDate) : { current: 0, arrears: 0 };

    const amounts = {
      registrationFee: registrationFee(txn, v, totalValue, cc),
      mvt: mvt.current,
      mvtArrears: mvt.arrears,
      incomeTax: incomeTax(txn, v, ladenWeight, yearsMultiplier, filer, cc),
      lifetimeToken: lifetimeTokenTax(txn, base, yearsElapsed),
      hpa: hpaFee(!!raw.hpa, v, cc),
      cardFee: 1300,
      professionalTax: professionalTax(txn, v, yearsMultiplier),
      lateFee: lateRegistrationFee(txn, days, v, raw.commercialSub),
      markFee: additionalMarkFee(v, cc, raw.commercialSub),
      platform: 15,
      cvt: capitalValueTax(txn, !!raw.cvt, cc, invDate, regDate, totalValue),
      rebate: rebate(regDate, mvt.current),
      transferFee: transferFee(txn, v, cc, raw.commercialSub),
      wht: withholdingTax(txn, v, cc, yearsElapsed, filer),
      advanceWht: advanceWHT(txn, cc, filer),
      transferLtt: transferLTT(txn, v, raw.motorCycleSub, cc, invDate, regDate)
    };

    const visible = {
      transferFee: isTransferCase(txn),
      wht: isTransferCase(txn),
      transferLtt: isTransferCase(txn),
      advanceWht: txn === 'nrt'
    };

    const lines = Object.keys(LABELS)
      .filter((k) => visible[k] !== false)
      .map((k) => ({ id: k, label: LABELS[k], amount: Math.round(amounts[k] * 100) / 100 }));

    const total = lines.reduce((s, l) => s + l.amount, 0);

    return {
      ok: true,
      lines,
      total: Math.round(total * 100) / 100,
      warnings,
      meta: {
        totalValue, cc, days, yearsElapsed, usesMVT,
        invoiceFY: fyLabel(fyI), regFY: fyLabel(fyR)
      }
    };
  }

  const engine = { compute, parseDate, fiscalYear, fyLabel, LABELS };
  if (typeof module !== 'undefined' && module.exports) module.exports = engine;
  root.ExciseEngine = engine;

  // ===================================================================== UI
  if (typeof document === 'undefined') return;

  const $ = (id) => document.getElementById(id);
  // One saved form per signed-in user, so people sharing a computer don't see each other's inputs
  const calcRoot = document.querySelector('[data-user]');
  const STORE_KEY = 'excise-estimator-v2:' + (calcRoot ? calcRoot.getAttribute('data-user') : 'anon');
  const DEFAULTS = {
    txn: 'nrt', vehicle: 'car', motorCycleSub: 'standard', commercialSub: 'standard',
    cc: '1300', kw: '', ladenWeight: '', invoiceValue: '5200000', advanceTax: '0',
    taxStatus: 'filer', owner: '2nd', cvt: 'no', hpa: 'no',
    invoiceDate: '2026-07-01', regDate: '2026-10-20'
  };
  const FIELDS = ['motorCycleSub', 'commercialSub', 'cc', 'kw', 'ladenWeight', 'invoiceValue', 'advanceTax', 'owner', 'invoiceDate', 'regDate'];
  const RADIOS = ['txn', 'vehicle', 'taxStatus', 'cvt', 'hpa'];

  const rs = (n) => {
    const neg = n < 0;
    const s = Math.abs(n).toLocaleString('en-PK', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    return (neg ? '−' : '') + 'Rs ' + s;
  };

  function lakh(n) {
    if (!n) return '';
    if (n >= 1e7) return '≈ ' + (n / 1e7).toLocaleString('en-PK', { maximumFractionDigits: 2 }) + ' crore';
    if (n >= 1e5) return '≈ ' + (n / 1e5).toLocaleString('en-PK', { maximumFractionDigits: 2 }) + ' lakh';
    return '';
  }

  function radioVal(name) {
    const el = document.querySelector('input[name="' + name + '"]:checked');
    return el ? el.value : '';
  }

  function setRadio(name, value) {
    const el = document.querySelector('input[name="' + name + '"][value="' + value + '"]');
    if (el) el.checked = true;
  }

  function readState() {
    const s = {};
    RADIOS.forEach((n) => (s[n] = radioVal(n)));
    FIELDS.forEach((f) => (s[f] = $(f).value));
    return s;
  }

  function applyState(s) {
    RADIOS.forEach((n) => setRadio(n, s[n]));
    FIELDS.forEach((f) => { if (s[f] !== undefined) $(f).value = s[f]; });
  }

  function updateVisibility(s) {
    $('grpMotorCycleSub').hidden = s.vehicle !== 'motorcycle';
    $('grpCommercialSub').hidden = s.vehicle !== 'commercial';
    $('grpWeight').hidden = s.vehicle !== 'commercial';
    $('grpKW').hidden = s.vehicle !== 'ev';
    $('grpCC').hidden = s.vehicle === 'ev';

    const owner = $('owner');
    if (s.txn === 'new') { owner.value = '1st'; owner.disabled = true; }
    else owner.disabled = false;

    $('invoiceDateLabel').textContent = s.txn === 'transfer' ? 'Original registration date' : 'Invoice date';
    $('regDateLabel').textContent = s.txn === 'transfer' ? 'Transfer date' : 'Registration date';
  }

  function render() {
    const s = readState();
    updateVisibility(s);
    try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (e) { /* storage unavailable */ }

    const r = compute({
      txn: s.txn, vehicle: s.vehicle, motorCycleSub: s.motorCycleSub, commercialSub: s.commercialSub,
      cc: s.cc, kw: s.kw, ladenWeight: s.ladenWeight, invoiceValue: s.invoiceValue, advanceTax: s.advanceTax,
      filer: s.taxStatus === 'filer', cvt: s.cvt === 'yes', hpa: s.hpa === 'yes',
      invoiceDate: s.invoiceDate, regDate: s.regDate
    });

    $('totalValueOut').textContent = rs(r.meta.totalValue);
    $('invoiceHint').textContent = lakh(num(s.invoiceValue));
    $('ccEquiv').textContent = r.meta.cc ? '≈ ' + Math.round(r.meta.cc).toLocaleString('en-PK') + ' cc equivalent' : '';

    const warn = $('warnings');
    warn.innerHTML = '';
    r.warnings.forEach((w) => { const li = document.createElement('li'); li.textContent = w; warn.appendChild(li); });
    warn.hidden = r.warnings.length === 0;

    const body = $('lines');
    body.innerHTML = '';
    r.lines.forEach((l, i) => {
      const tr = document.createElement('tr');
      if (l.amount === 0) tr.className = 'zero';
      if (l.amount < 0) tr.className = 'credit';
      tr.innerHTML = '<td class="sr"></td><td class="desc"></td><td class="amt"></td>';
      tr.children[0].textContent = String(i + 1).padStart(2, '0');
      tr.children[1].textContent = l.label;
      tr.children[2].textContent = rs(l.amount);
      body.appendChild(tr);
    });

    $('total').textContent = rs(r.total);
    $('mobileTotal').textContent = rs(r.total);

    const m = r.meta;
    $('chips').innerHTML = '';
    if (r.ok) {
      [
        ['Invoice FY', m.invoiceFY],
        ['Registration FY', m.regFY],
        ['Fiscal years elapsed', String(m.yearsElapsed)],
        ['Days to register', String(Math.max(0, m.days))],
        ['Tax basis', m.usesMVT ? 'Motor vehicle tax' : 'Lifetime token']
      ].forEach(([k, val]) => {
        const div = document.createElement('div');
        div.innerHTML = '<dt></dt><dd></dd>';
        div.children[0].textContent = k;
        div.children[1].textContent = val;
        $('chips').appendChild(div);
      });
    }

    const txnName = { new: 'New registration', nrt: 'New registration + transfer', transfer: 'Transfer of ownership' }[s.txn];
    const vName = { motorcycle: 'Motor cycle', car: 'Motor car', commercial: 'Commercial', ev: 'Electric vehicle' }[s.vehicle];
    $('summaryLine').textContent = txnName + ' · ' + vName + ' · ' + (s.taxStatus === 'filer' ? 'Filer' : 'Non-filer');

    render.lastState = s;
    render.lastResult = r;
    render.lastText = [
      'Excise estimate — ' + $('summaryLine').textContent,
      ...r.lines.map((l, i) => (i + 1) + '. ' + l.label + ': ' + rs(l.amount)),
      'Total: ' + rs(r.total)
    ].join('\n');
  }

  function init() {
    let saved = null;
    const preload = $('preload');
    try {
      saved = preload ? JSON.parse(preload.textContent) : JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    } catch (e) { saved = null; }
    applyState(Object.assign({}, DEFAULTS, saved || {}));

    $('form').addEventListener('input', render);
    $('form').addEventListener('change', render);
    $('form').addEventListener('submit', (e) => e.preventDefault());

    $('resetBtn').addEventListener('click', () => { applyState(DEFAULTS); render(); });

    $('copyBtn').addEventListener('click', () => {
      const btn = $('copyBtn');
      const done = () => { btn.textContent = 'Copied'; setTimeout(() => (btn.textContent = 'Copy breakdown'), 1600); };
      try {
        navigator.clipboard.writeText(render.lastText).then(done, () => fallbackCopy(done));
      } catch (e) { fallbackCopy(done); }
    });

    $('printBtn').addEventListener('click', () => window.print());
    $('saveBtn').addEventListener('click', saveEstimate);

    render();
  }

  async function saveEstimate() {
    const ui = window.ExciseUI;
    const r = render.lastResult;
    if (!r || !r.ok) { ui.toast(r && r.warnings[0] ? r.warnings[0] : 'Complete the form first.', { error: true }); return; }
    const summary = $('summaryLine').textContent;
    const title = window.prompt('Name this estimate (e.g. customer or vehicle):', summary);
    if (title === null) return;

    const btn = $('saveBtn');
    btn.disabled = true;
    try {
      await ui.api('POST', '/api/estimates', {
        title: title.trim() || summary,
        summary,
        total: r.total,
        inputs: render.lastState,
        lines: r.lines.map((l) => ({ label: l.label, amount: l.amount }))
      });
      ui.toast('Estimate saved.', { link: { href: '/estimates', text: 'View saved' } });
    } catch (e) {
      ui.toast(e.message, { error: true });
    } finally {
      btn.disabled = false;
    }
  }

  function fallbackCopy(done) {
    const ta = document.createElement('textarea');
    ta.value = render.lastText;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { /* user can select manually */ }
    ta.remove();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(typeof window !== 'undefined' ? window : globalThis);
