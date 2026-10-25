/*
 * browser-cleaner.js — 表格清洗核心逻辑（浏览器端零依赖版）
 *
 * 与 clean_my_table.py 同一套判据（表头别名 / 日期归一 / 金额欧式美式 / 邮箱校验 /
 * 电话归一 / 币种推断 / 去重合并 / 行数守恒），但完全在浏览器本地跑：
 *   - 文件不离开用户电脑（无上传、无服务器）
 *   - 访客不需要装 Python、不需要注册、不需要下载
 *
 * 用法：
 *   浏览器：<script src="browser-cleaner.js"></script> 后用 window.BrowserCleaner
 *   Node  ：const BC = require('./browser-cleaner.js'); BC.selfTest()
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BrowserCleaner = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ---------------------------------------------------------------- 基础
  function cleanText(v) {
    if (v === null || v === undefined) return '';
    return String(v).replace(/\s+/g, ' ').trim();
  }
  function normHeader(text) { return cleanText(text).toLowerCase().replace(/\s+/g, ''); }

  // ---------------------------------------------------------------- 别名表
  const COLUMN_ALIASES = {
    name: ['name', 'company', 'company_name', 'vendor', 'supplier', 'vendor name',
      'supplier name', 'customer', 'client', '名称', '公司', '公司名', '供应商', '客户', '单位', '商户'],
    email: ['email', 'e-mail', 'email_address', 'email address', 'mail',
      'contact email', '邮箱', '电子邮箱', '邮件'],
    phone: ['phone', 'phone_no', 'phone number', 'telephone', 'mobile', 'tel',
      'contact', 'contact_no', '电话', '手机', '联系电话', '联系方式'],
    date: ['date', 'order_date', 'delivery date', 'ordered', 'transaction date',
      'created_at', 'invoice_date', '日期', '时间', '下单日期', '订单日期', '开票日期', '交易日期'],
    amount: ['amount', 'total', 'value', 'order value', 'sum', 'price', 'cost', 'revenue',
      'amount usd', 'total price', '金额', '价格', '总价', '合计', '金额(含税)', '应付金额'],
    currency: ['currency', 'ccy', 'curr', 'currency code', '币种', '货币', '结算币种'],
    qty: ['qty', 'quantity', 'units', 'count', '数量', '件数', '台数']
  };

  const CURRENCY_ALIASES = {
    usd: 'USD', '$': 'USD', 'us$': 'USD', dollar: 'USD', dollars: 'USD', '美元': 'USD',
    eur: 'EUR', '€': 'EUR', euro: 'EUR', euros: 'EUR', '欧元': 'EUR',
    jpy: 'JPY', '¥': 'JPY', yen: 'JPY', '日元': 'JPY',
    gbp: 'GBP', '£': 'GBP', pound: 'GBP', '英镑': 'GBP',
    cny: 'CNY', rmb: 'CNY', yuan: 'CNY', '人民币': 'CNY', '元': 'CNY'
  };

  const LEGAL_SUFFIXES = ['Ltd', 'Ltd.', 'Inc', 'Inc.', 'LLC', 'Co', 'Co.', 'Corp', 'Corp.', 'GmbH', 'Oy'];
  const MONTHS = {
    jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
    jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12
  };

  // ---------------------------------------------------------------- CSV 解析
  function parseCSV(text) {
    const src = String(text).replace(/^\uFEFF/, '');
    const rows = [];
    let row = [], field = '', inQuotes = false, i = 0;
    while (i < src.length) {
      const ch = src[i];
      if (inQuotes) {
        if (ch === '"') {
          if (src[i + 1] === '"') { field += '"'; i += 2; continue; }
          inQuotes = false; i++; continue;
        }
        field += ch; i++; continue;
      }
      if (ch === '"') { inQuotes = true; i++; continue; }
      if (ch === ',') { row.push(field); field = ''; i++; continue; }
      if (ch === '\r') { i++; continue; }
      if (ch === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; continue; }
      field += ch; i++;
    }
    if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
    const cleaned = rows.filter(r => r.some(c => cleanText(c) !== ''));
    if (!cleaned.length) return { headers: [], rows: [] };
    const headers = cleaned[0].map(h => cleanText(h));
    const body = cleaned.slice(1).map(r => {
      const o = {};
      headers.forEach((h, idx) => { o[h] = r[idx] === undefined ? '' : r[idx]; });
      return o;
    });
    return { headers, rows: body };
  }

  function toCSV(headers, rows) {
    const esc = v => {
      const s = v === null || v === undefined ? '' : String(v);
      return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const lines = [headers.map(esc).join(',')];
    rows.forEach(r => lines.push(headers.map(h => esc(r[h])).join(',')));
    return lines.join('\r\n') + '\r\n';
  }

  // ---------------------------------------------------------------- 字段清洗
  function cleanName(value) {
    const raw = cleanText(value);
    if (!raw) return { value: '', issue: 'name_missing' };
    const fixed = raw.replace(/\s*,\s*/g, ', ');
    const pretty = fixed.split(' ').map(w => {
      if (LEGAL_SUFFIXES.indexOf(w) >= 0) return w.replace(/\.$/, '');
      if (w === w.toUpperCase() && w.length > 1) return w;
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join(' ');
    return { value: pretty, issue: pretty !== raw ? 'name_normalised' : null };
  }

  function cleanEmail(value) {
    const raw = cleanText(value).toLowerCase();
    if (!raw) return { value: '', issue: 'email_missing' };
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw)) return { value: '', issue: 'email_invalid' };
    return { value: raw, issue: null };
  }

  function cleanPhone(value) {
    const raw = cleanText(value);
    if (!raw) return { value: '', issue: 'phone_missing' };
    let digits = raw.replace(/\D/g, '');
    digits = digits.replace(/(?:ext|x|分机)\.?\d+$/i, '');
    if (digits.indexOf('00') === 0) digits = digits.slice(2);
    if (!digits) return { value: '', issue: 'phone_invalid' };
    return { value: digits, issue: raw !== digits ? 'phone_normalised' : null };
  }

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  function cleanDate(value) {
    const raw = cleanText(value);
    if (!raw) return { value: '', issue: 'date_missing' };
    const ymd = raw.match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
    if (ymd) {
      const y = +ymd[1], mo = +ymd[2], d = +ymd[3];
      if (mo >= 1 && mo <= 12 && d >= 1 && d <= 31) {
        const out = y + '-' + pad(mo) + '-' + pad(d);
        return { value: out, issue: out === raw ? null : (raw.length === 10 ? 'date_format_normalised' : 'date_extracted') };
      }
    }
    // d.m.YYYY / d/m/YYYY
    const dmy = raw.match(/^(\d{1,2})[./](\d{1,2})[./](\d{4})$/);
    if (dmy) {
      const d = +dmy[1], mo = +dmy[2], y = +dmy[3];
      if (mo >= 1 && mo <= 12 && d >= 1 && d <= 31) {
        return { value: y + '-' + pad(mo) + '-' + pad(d), issue: 'date_format_normalised' };
      }
    }
    // Jan 8 2024 / 8 Jan 2024
    const mdy = raw.match(/^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})$/);
    if (mdy && MONTHS[mdy[1].toLowerCase()]) {
      return { value: mdy[3] + '-' + pad(MONTHS[mdy[1].toLowerCase()]) + '-' + pad(+mdy[2]), issue: 'date_format_normalised' };
    }
    const dmy2 = raw.match(/^(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})$/);
    if (dmy2 && MONTHS[dmy2[2].toLowerCase()]) {
      return { value: dmy2[3] + '-' + pad(MONTHS[dmy2[2].toLowerCase()]) + '-' + pad(+dmy2[1]), issue: 'date_format_normalised' };
    }
    // 2024-01-05T10:00:00
    const iso = raw.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(:\d{2})?$/);
    if (iso) return { value: iso[1], issue: 'date_format_normalised' };
    return { value: '', issue: 'date_unparsable' };
  }

  function cleanAmount(value) {
    const raw = cleanText(value);
    if (!raw) return { value: null, issue: 'amount_missing' };
    let s = raw;
    if (s.charAt(0) === '€') s = 'EUR ' + s.slice(1);
    else if (s.charAt(0) === '¥') s = 'JPY ' + s.slice(1);
    else if (s.charAt(0) === '$') s = 'USD ' + s.slice(1);
    const negative = s.charAt(0) === '-' || (s.charAt(0) === '(' && s.charAt(s.length - 1) === ')');
    let c = s.replace(/[^\d.,\-]/g, '');
    if (c.indexOf(',') >= 0 && c.indexOf('.') >= 0) {
      if (c.lastIndexOf(',') > c.lastIndexOf('.')) c = c.replace(/\./g, '').replace(',', '.');
      else c = c.replace(/,/g, '');
    } else if (c.indexOf(',') >= 0) {
      const frac = c.split(',').pop();
      c = (frac.length === 1 || frac.length === 2) ? c.replace(',', '.') : c.replace(/,/g, '');
    }
    c = c.replace(/-/g, '');
    if (!c || c === '.') return { value: null, issue: 'amount_invalid' };
    const num = parseFloat(c);
    if (isNaN(num)) return { value: null, issue: 'amount_invalid' };
    const amountValue = negative ? -num : num;
    const canonical = amountValue.toFixed(2);
    return { value: amountValue, issue: canonical !== raw ? 'amount_normalised' : null };
  }

  function cleanCurrency(value, amountText) {
    const raw = cleanText(value).toLowerCase();
    if (CURRENCY_ALIASES[raw]) return { value: CURRENCY_ALIASES[raw], issue: null };
    const m = cleanText(value).toUpperCase().match(/(USD|EUR|JPY|GBP|CNY)/);
    if (m) return { value: m[1], issue: 'currency_normalised' };
    const t = cleanText(amountText || '');
    if (t.indexOf('€') >= 0) return { value: 'EUR', issue: 'currency_inferred_from_amount' };
    if (t.indexOf('¥') >= 0) return { value: 'JPY', issue: 'currency_inferred_from_amount' };
    if (t.indexOf('$') >= 0) return { value: 'USD', issue: 'currency_inferred_from_amount' };
    return { value: '', issue: 'currency_missing' };
  }

  function cleanQty(value) {
    const raw = cleanText(value);
    if (!raw) return { value: null, issue: null };
    const digits = raw.replace(/[^0-9.]/g, '');
    if (!digits) return { value: null, issue: 'qty_invalid' };
    const n = parseFloat(digits);
    if (isNaN(n)) return { value: null, issue: 'qty_invalid' };
    return { value: n, issue: null };
  }

  // ---------------------------------------------------------------- 表头角色识别
  function detectRoles(headers) {
    const mapping = {};
    const used = {};
    const normalised = {};
    headers.forEach(h => { normalised[h] = normHeader(h); });
    Object.keys(COLUMN_ALIASES).forEach(role => {
      const aliases = COLUMN_ALIASES[role];
      for (let a = 0; a < aliases.length; a++) {
        const an = normHeader(aliases[a]);
        for (let hi = 0; hi < headers.length; hi++) {
          const h = headers[hi];
          if (used[h]) continue;
          const nh = normalised[h];
          if (nh === an || (an.length >= 4 && nh.indexOf(an) >= 0) || (nh.length >= 4 && an.indexOf(nh) >= 0)) {
            mapping[h] = role;
            used[h] = true;
            break;
          }
        }
        if (mapping[headers.filter(x => mapping[x])[0]] === role && Object.keys(mapping).some(k => mapping[k] === role)) break;
        if (Object.keys(mapping).some(k => mapping[k] === role)) break;
      }
    });
    return mapping;
  }

  // ---------------------------------------------------------------- 主流程
  const FIELDS = ['name', 'email', 'phone', 'date', 'amount', 'currency', 'qty'];

  function cleanTable(text, options) {
    const opts = options || {};
    const source = opts.source || 'paste';
    const parsed = parseCSV(text);
    const headers = parsed.headers;
    const rawRows = parsed.rows;
    const roles = detectRoles(headers);
    const roleHeaders = {};
    Object.keys(roles).forEach(h => { roleHeaders[roles[h]] = h; });

    const cleanRows = [];
    const reviewRows = [];
    const mergedRows = [];
    const issues = {};
    const seenEmail = {};
    const seenPhone = {};
    const seenNameOnly = {};

    function bump(code) { issues[code] = (issues[code] || 0) + 1; }

    rawRows.forEach(function (row, idx) {
      const srcRow = idx + 2; // 1-based，含表头
      const out = { source_row: srcRow, source_file: source };
      const problems = [];

      FIELDS.forEach(function (field) {
        const h = roleHeaders[field];
        const raw = h ? row[h] : '';
        let res = { value: '', issue: null };
        if (field === 'name') res = cleanName(raw);
        else if (field === 'email') res = cleanEmail(raw);
        else if (field === 'phone') res = cleanPhone(raw);
        else if (field === 'date') res = cleanDate(raw);
        else if (field === 'amount') res = cleanAmount(raw);
        else if (field === 'currency') res = cleanCurrency(raw, roleHeaders.amount ? row[roleHeaders.amount] : '');
        else if (field === 'qty') res = cleanQty(raw);
        out[field] = res.value === null ? '' : res.value;
        if (res.issue) {
          bump(res.issue);
          // 缺失类问题只在字段确实被识别到时才算"待复核"
          if (h && /_missing$|_invalid$|_unparsable$/.test(res.issue)) {
            problems.push({ field: field, reason: res.issue, raw: cleanText(raw) });
          }
        }
      });

      // 必须有名字，否则整行进复核
      if (!out.name) problems.push({ field: 'name', reason: 'name_missing', raw: '' });

      // 去重：同邮箱 / 同电话 视为同一主体；两者都缺时才用同名判重
      const nameKey = cleanText(out.name).toLowerCase();
      const emailKey = out.email ? out.email.toLowerCase() : '';
      const phoneKey = out.phone ? out.phone : '';
      let hit = null;
      if (emailKey && seenEmail[emailKey]) hit = seenEmail[emailKey];
      else if (phoneKey && seenPhone[phoneKey]) hit = seenPhone[phoneKey];
      else if (!emailKey && !phoneKey && nameKey && seenNameOnly[nameKey]) hit = seenNameOnly[nameKey];
      if (hit) {
        hit.merged += 1;
        mergedRows.push({ source_row: srcRow, source_file: source, name: out.name, merged_into_row: hit.row });
        bump('duplicate_merged');
        return;
      }
      const rec = { row: srcRow, merged: 0 };
      if (emailKey) seenEmail[emailKey] = rec;
      if (phoneKey) seenPhone[phoneKey] = rec;
      if (nameKey && !emailKey && !phoneKey) seenNameOnly[nameKey] = rec;

      if (problems.length) {
        reviewRows.push({
          source_row: srcRow, source_file: source,
          name: out.name, email: out.email, phone: out.phone, date: out.date,
          amount: out.amount, currency: out.currency, qty: out.qty,
          reason: problems.map(p => p.field + ':' + p.reason).join('; '),
          raw: problems.map(p => p.field + '=' + p.raw).join(' | ')
        });
      } else {
        cleanRows.push(out);
      }
    });

    const outHeaders = FIELDS.filter(f => cleanRows.some(r => r[f] !== '' && r[f] !== undefined));
    const report = {
      source: source,
      generated_at: new Date().toISOString(),
      rows_in: rawRows.length,
      rows_clean: cleanRows.length,
      rows_review: reviewRows.length,
      rows_merged: mergedRows.length,
      row_conservation: rawRows.length === cleanRows.length + reviewRows.length + mergedRows.length,
      detected_roles: roles,
      issues: issues
    };

    return {
      headers: headers,
      roles: roles,
      cleanHeaders: outHeaders.length ? outHeaders : FIELDS,
      cleanRows: cleanRows,
      reviewRows: reviewRows,
      mergedRows: mergedRows,
      report: report
    };
  }

  // ---------------------------------------------------------------- 自检
  function selfTest() {
    const checks = [];
    function check(name, cond, detail) {
      checks.push({ name: name, ok: !!cond, detail: detail || '' });
    }

    const messy = [
      '供应商,联系方式,邮箱,订单日期,金额',
      '"北京 星海 科技有限公司",138-0013-8000,INFO@EXAMPLE.COM,2024/1/5,"1.234,56"',
      '"Beijing Xinghai Tech Co. Ltd",+86 138 0013 8000,info@example.com,2024年1月5日,"1,234.56"',
      '无名供应商,13900000000,not-an-email,Jan 8 2024,240 USD',
      '北京 星海 科技有限公司,,,2024-02-01,(240)'
    ].join('\n');

    const r = cleanTable(messy, { source: 'selftest' });

    check('行数守恒（入 = 净 + 复核 + 合并）', r.report.row_conservation,
      JSON.stringify([r.report.rows_in, r.report.rows_clean, r.report.rows_review, r.report.rows_merged]));
    check('合并行被识别（同名同邮箱）', r.report.rows_merged === 1, 'merged=' + r.report.rows_merged);
    check('表头角色识别 name', r.roles['供应商'] === 'name', JSON.stringify(r.roles));
    check('表头角色识别 email', r.roles['邮箱'] === 'email', JSON.stringify(r.roles));
    check('表头角色识别 date', r.roles['订单日期'] === 'date', JSON.stringify(r.roles));
    check('表头角色识别 amount', r.roles['金额'] === 'amount', JSON.stringify(r.roles));
    check('欧式金额 1.234,56 → 1234.56', r.cleanRows.some(x => x.amount === 1234.56) ||
      r.reviewRows.some(x => String(x.amount) === '1234.56'), JSON.stringify(r.cleanRows.map(x => x.amount)));
    check('括号负数 (240) → -240', r.cleanRows.some(x => x.amount === -240) ||
      r.reviewRows.some(x => String(x.amount) === '-240'), JSON.stringify(r.cleanRows.map(x => x.amount)));
    check('邮箱大小写归一', r.cleanRows.concat(r.reviewRows).some(x => x.email === 'info@example.com'),
      JSON.stringify(r.cleanRows.concat(r.reviewRows).map(x => x.email)));
    check('非法邮箱进复核表', r.reviewRows.some(x => /email:email_invalid/.test(x.reason)), JSON.stringify(r.reviewRows.map(x => x.reason)));
    check('日期 2024/1/5 → 2024-01-05', r.cleanRows.concat(r.reviewRows).some(x => x.date === '2024-01-05'),
      JSON.stringify(r.cleanRows.concat(r.reviewRows).map(x => x.date)));
    check('缺字段的行进复核表', r.reviewRows.some(x => /_missing/.test(x.reason)), JSON.stringify(r.reviewRows.map(x => x.reason)));
    check('电话去掉分隔符只留数字', r.cleanRows.concat(r.reviewRows).every(x => x.phone === '' || /^\d+$/.test(x.phone)),
      JSON.stringify(r.cleanRows.concat(r.reviewRows).map(x => x.phone)));

    const rt = parseCSV('a,b\n"x,1",2\n"he said ""hi""",3\n');
    check('CSV 引号转义解析正确', rt.rows.length === 2 && rt.rows[0]['a'] === 'x,1' && rt.rows[1]['a'] === 'he said "hi"',
      JSON.stringify(rt.rows));
    const csvOut = toCSV(['a'], [{ a: 'x,y' }]);
    check('CSV 输出转义正确', csvOut.indexOf('"x,y"') >= 0, JSON.stringify(csvOut));

    return checks;
  }

  return {
    parseCSV: parseCSV,
    toCSV: toCSV,
    detectRoles: detectRoles,
    cleanTable: cleanTable,
    cleanName: cleanName,
    cleanEmail: cleanEmail,
    cleanPhone: cleanPhone,
    cleanDate: cleanDate,
    cleanAmount: cleanAmount,
    cleanCurrency: cleanCurrency,
    cleanQty: cleanQty,
    selfTest: selfTest,
    FIELDS: FIELDS
  };
});
