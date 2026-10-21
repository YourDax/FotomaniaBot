/* Раздел «Импорт таблицы». */
import { loadContacts } from './contacts.js';
import { $, api, esc, qa, S } from './core.js';
import { loadSchools } from './schools.js';
import { toast } from './ui.js';

// --- Импорт таблицы ---------------------------------------------------------

export const IMPORT_FIELDS = [
  { value: 'class_name', label: 'Класс', required: true },
  { value: 'kr_name', label: 'ФИО КР', required: true },
  { value: 'kr_phone', label: 'Телефон КР', required: true },
  { value: 'rk_name', label: 'ФИО РК', required: true },
  { value: 'rk_phone', label: 'Телефон РК', required: true },
];

export function normalizeHeader(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[^а-яa-z0-9]+/g, ' ')
    .trim();
}

export function detectField(header) {
  // Сравниваем целые слова: иначе «Первоклассник» или «класса» в описании
  // столбца ошибочно считаются колонкой «Класс».
  const words = ` ${normalizeHeader(header)} `;
  const has = (...terms) => terms.some((term) => words.includes(` ${term} `));
  if (has('класс', 'class')) return 'class_name';
  if (has('кр фио', 'фио кр', 'ф и о кр', 'красный руководитель', 'кл рук', 'классный руководитель')) return 'kr_name';
  if (has('кр телефон', 'телефон кр', 'тел кр', 'номер кр', 'кр тел')) return 'kr_phone';
  if (has('рк фио', 'фио рк', 'ф и о рк', 'родительский комитет', 'родитель комитет', 'рк руководитель')) return 'rk_name';
  if (has('рк телефон', 'телефон рк', 'тел рк', 'номер рк', 'рк тел')) return 'rk_phone';
  if (has('фио', 'ф и о', 'name')) return 'kr_name';
  if (has('телефон', 'phone', 'тел')) return 'kr_phone';
  return '';
}

// Каждое поле назначается только первому подходящему столбцу файла.
export function detectMapping(headers) {
  const mapping = {};
  const taken = new Set();
  headers.forEach((header) => {
    const field = detectField(header);
    if (field && !taken.has(field)) {
      taken.add(field);
      mapping[header] = field;
    } else {
      mapping[header] = '';
    }
  });
  return mapping;
}

export function setImportStep(step) {
  S.importUi.step = step;
  qa('#importStepper span').forEach((node) => {
    const value = Number(node.dataset.step);
    node.classList.toggle('active', value === step);
    node.classList.toggle('done', value < step);
  });
}

export function readImportFile(file) {
  S.importUi.fileName = file ? file.name : '';
  $('importFileName').innerHTML = file
    ? `<b>${esc(file.name)}</b> · ${Math.max(1, Math.round(file.size / 1024))} КБ`
    : 'Файл не выбран. Можно перетащить файл в эту область.';
  $('importPreviewBtn').disabled = !file;
}

export async function previewImport() {
  const input = $('importFile');
  if (!input.files || !input.files.length) {
    toast('Сначала выберите файл', 'warn');
    return;
  }
  const form = new FormData();
  form.append('file', input.files[0]);
  const data = await api('/imports/preview', { method: 'POST', body: form });
  S.importUi.headers = data.headers || [];
  S.importUi.rows = data.rows || [];
  S.importUi.mapping = detectMapping(S.importUi.headers);
  S.importUi.showAll = false;
  renderImport();
  setImportStep(2);
  $('importStep').classList.remove('hidden');
  $('importResult').innerHTML = '';
  toast(`Файл прочитан: строк ${data.total_rows || S.importUi.rows.length}, найдена строка заголовков №${data.header_row || 1}`);
}

export function importRowQuality() {
  const ui = S.importUi;
  const classHeader = Object.keys(ui.mapping).find((header) => ui.mapping[header] === 'class_name');
  const nameHeaders = Object.keys(ui.mapping).filter((header) => ['kr_name', 'rk_name'].includes(ui.mapping[header]));
  let withContacts = 0;
  let withoutClass = 0;
  let empty = 0;
  let lastClass = '';
  ui.rows.forEach((row) => {
    const hasContact = nameHeaders.some((header) => String(row[header] || '').trim());
    const classValue = classHeader ? String(row[classHeader] || '').trim() : '';
    if (classValue) lastClass = classValue;
    const hasClass = classValue || lastClass;
    if (!hasContact && !hasClass) empty += 1;
    else if (hasContact && !hasClass) withoutClass += 1;
    else if (hasContact) withContacts += 1;
  });
  return { withContacts, withoutClass, empty, total: ui.rows.length };
}

export function renderImport() {
  const ui = S.importUi;
  const detected = ui.headers.map((header) => ui.mapping[header] || '');
  const missing = IMPORT_FIELDS.filter((field) => !detected.includes(field.value));
  const duplicates = detected.filter((value, index) => value && detected.indexOf(value) !== index);
  const quality = importRowQuality();

  const notices = [];
  if (!ui.headers.length) {
    notices.push('<div class="notice warn">В файле не найдено ни одного столбца с данными.</div>');
  } else if (missing.length) {
    notices.push(
      `<div class="notice warn">Не определены столбцы: ${missing.map((field) => esc(field.label)).join(', ')}. Укажите их вручную — без них часть контактов не импортируется. ` +
      `Импорт требует как минимум столбец «Класс» и одну пару «ФИО/телефон».</div>`,
    );
  } else {
    notices.push('<div class="notice">Все обязательные столбцы определены. Проверьте сопоставление перед импортом.</div>');
  }
  if (duplicates.length) {
    notices.push(`<div class="notice warn">Один и тот же столбец назначен несколько раз: ${duplicates.map((value) => esc(value)).join(', ')}. Лишние назначения будут проигнорированы.</div>`);
  }
  notices.push(
    `<div class="notice info">Строк в файле: ${quality.total}. Готово к импорту: ${quality.withContacts}` +
    `${quality.withoutClass ? `, без класса: ${quality.withoutClass}` : ''}` +
    `${quality.empty ? `, полностью пустых: ${quality.empty}` : ''}. ` +
    'Повторяющиеся пары «класс + ФИО + роль» сервер пропустит.</div>',
  );
  $('importWarnings').innerHTML = notices.join('');

  $('importMapping').innerHTML = ui.headers.map((header) => `
    <div class="field">
      <span>${esc(header || '(без названия)')}${detected[ui.headers.indexOf(header)] ? ' <span class="badge ok">определено</span>' : ''}</span>
      <select data-header="${esc(header)}">
        <option value="">Не использовать</option>
        ${IMPORT_FIELDS.map((field) => `<option value="${field.value}" ${detected[ui.headers.indexOf(header)] === field.value ? 'selected' : ''}>${esc(field.label)}${field.required ? ' *' : ''}</option>`).join('')}
      </select>
    </div>`).join('');
  qa('#importMapping select').forEach((select) => {
    select.addEventListener('change', () => {
      S.importUi.mapping[select.dataset.header] = select.value;
      renderImport();
    });
  });

  const limit = ui.showAll ? ui.rows.length : Math.min(ui.rows.length, 10);
  $('importRowInfo').textContent = ui.rows.length
    ? `Показано ${limit} из ${ui.rows.length} строк`
    : 'Строк с данными нет';
  $('importShowAll').textContent = ui.showAll ? 'Показать первые 10 строк' : 'Показать все строки';
  $('importShowAll').disabled = ui.rows.length <= 10;
  $('importHead').innerHTML = `<tr>${ui.headers.map((header) => `<th>${esc(header)}</th>`).join('')}</tr>`;
  $('importRows').innerHTML = ui.rows.slice(0, limit).map((row) => `
    <tr>${ui.headers.map((header) => {
      const value = String(row[header] === undefined ? '' : row[header]);
      const field = ui.mapping[header];
      const required = IMPORT_FIELDS.some((item) => item.value === field && item.required);
      return `<td>${value ? esc(value) : (required ? '<span class="badge warn">пусто</span>' : '')}</td>`;
    }).join('')}</tr>`).join('') || '<tr><td class="empty">Нет данных</td></tr>';
}

export async function runImport() {
  const ui = S.importUi;
  const schoolSelect = $('importSchoolSelect');
  const newSchool = ($('importSchoolNew').value || '').trim();
  const schoolName = newSchool || (schoolSelect.value ? schoolSelect.value : '');
  if (!schoolName) {
    toast('Выберите школу в списке или введите название новой школы', 'warn');
    return;
  }
  const mapped = Object.values(ui.mapping).filter(Boolean);
  if (!mapped.length) {
    toast('Назначьте хотя бы один столбец', 'warn');
    return;
  }
  if (!mapped.includes('class_name') || !mapped.some((value) => ['kr_name', 'rk_name'].includes(value))) {
    toast('Для импорта нужны столбец «Класс» и хотя бы один столбец с ФИО', 'warn');
    return;
  }
  const button = $('importRun');
  button.setAttribute('aria-busy', 'true');
  button.disabled = true;
  try {
    const result = await api('/imports/school-contacts', {
      method: 'POST',
      body: JSON.stringify({
        rows: ui.rows,
        mapping: ui.mapping,
        school_name: schoolName,
        duplicate_mode: 'update',
      }),
    });
    setImportStep(3);
    $('importResult').innerHTML =
      `<div class="notice">Импорт завершён. Добавлено контактов: <b>${result.created}</b>, класс исправлен: <b>${result.updated || 0}</b>, пропущено (уже были): <b>${result.skipped}</b>.</div>`;
    toast(`Импорт завершён: добавлено ${result.created}, исправлено классов ${result.updated || 0}, пропущено ${result.skipped}`);
    await loadSchools();
    await loadContacts().catch(() => {});
  } finally {
    button.removeAttribute('aria-busy');
    button.disabled = false;
  }
}

export function resetImport() {
  $('importFile').value = '';
  readImportFile(null);
  S.importUi.headers = [];
  S.importUi.rows = [];
  S.importUi.mapping = {};
  S.importUi.showAll = false;
  $('importStep').classList.add('hidden');
  $('importResult').innerHTML = '';
  $('importSchoolNew').value = '';
  setImportStep(1);
}
