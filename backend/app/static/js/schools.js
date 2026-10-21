/* Раздел «Школы и классы». */
import { renderPicker } from './campaigns.js';
import { $, api, esc, plural, qa, S, savePrefs } from './core.js';
import { confirmAction, promptAction, toast } from './ui.js';

// --- Школы и классы -------------------------------------------------------

export function contactCount(school, role) {
  return (school.classes || [])
    .flatMap((item) => item.contacts || [])
    .filter((contact) => !role || contact.role === role).length;
}

export function schoolOptions(selectedId, includeAllLabel) {
  const head = includeAllLabel ? `<option value="">${esc(includeAllLabel)}</option>` : '';
  return head + S.schools
    .map((school) => `<option value="${school.id}" ${Number(selectedId) === school.id ? 'selected' : ''}>${esc(school.name)}</option>`)
    .join('');
}

export function classOptions(schoolId, selectedId) {
  const school = S.schools.find((item) => item.id === Number(schoolId));
  const head = '<option value="">Все классы</option>';
  if (!school) return head;
  return head + (school.classes || [])
    .map((item) => `<option value="${item.id}" ${Number(selectedId) === item.id ? 'selected' : ''}>${esc(item.name)}</option>`)
    .join('');
}

export function renderSchoolOptions() {
  // Сохранённый фильтр мог указывать на удалённую школу или класс.
  const ui = S.contactsUi;
  const school = S.schools.find((item) => item.id === Number(ui.school));
  if (ui.school && !school) Object.assign(ui, { school: '', klass: '' });
  else if (ui.klass && !(school.classes || []).some((item) => item.id === Number(ui.klass))) ui.klass = '';
  $('importSchoolSelect').innerHTML = schoolOptions(null, 'Выберите школу');
  $('contactSchool').innerHTML = schoolOptions(S.contactsUi.school, 'Все школы');
  $('contactClass').innerHTML = classOptions(S.contactsUi.school, S.contactsUi.klass);
}

export function updateNavCounts() {
  const contacts = S.schools.reduce(
    (total, school) => total + (school.classes || []).reduce((sum, item) => sum + (item.contacts || []).length, 0),
    0,
  );
  $('navCountSchools').textContent = S.schools.length;
  $('navCountContacts').textContent = contacts;
  $('navCountCampaigns').textContent = S.campaigns.length;
}

export async function loadSchools() {
  S.schools = await api('/schools');
  renderSchoolOptions();
  renderSchools();
  renderPicker();
  updateNavCounts();
  return S.schools;
}

// --- Сворачивание школ и классов -------------------------------------------
// Ключи: s<id> — школа, c<id> — класс. Состояние общее для всех разделов,
// где встречаются школы (список школ, выбор получателей), и хранится в настройках.

export const schoolKey = (id) => `s${id}`;
export const classKey = (id) => `c${id}`;

export function saveCollapsed() {
  S.prefs.collapsed = Array.from(S.collapsed);
  savePrefs();
}

export function applyCollapsed(block, collapsed) {
  block.classList.toggle('is-collapsed', collapsed);
  const body = block.querySelector('.collapse-body');
  if (body) body.hidden = collapsed;
  qa('[data-action="collapse-toggle"]', block).forEach((node) => {
    node.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  });
}

export function toggleCollapse(element) {
  const block = element.closest('[data-collapse]');
  if (!block) return;
  const key = block.dataset.collapse;
  const collapsed = !S.collapsed.has(key);
  if (collapsed) S.collapsed.add(key);
  else S.collapsed.delete(key);
  applyCollapsed(block, collapsed);
  saveCollapsed();
  updateCollapseToggles();
}

const collapseScopes = () => [
  ['schools', $('schoolList'), $('schoolsCollapseToggle')],
  ['picker', $('campaignPicker'), $('pickerCollapseToggle')],
];

export function setAllCollapsed(scope, collapsed) {
  const container = scope === 'picker' ? $('campaignPicker') : $('schoolList');
  if (!container) return;
  container.querySelectorAll('[data-collapse]').forEach((block) => {
    const key = block.dataset.collapse;
    if (collapsed) S.collapsed.add(key);
    else S.collapsed.delete(key);
    applyCollapsed(block, collapsed);
  });
  saveCollapsed();
  updateCollapseToggles();
}

// Одна кнопка вместо пары: сворачивает, пока есть раскрытые школы, иначе разворачивает.
export function toggleAllCollapsed(scope) {
  const [, container] = collapseScopes().find(([name]) => name === scope);
  const anyOpen = qa(':scope > [data-collapse]', container).some((block) => !block.classList.contains('is-collapsed'));
  setAllCollapsed(scope, anyOpen);
}

export function updateCollapseToggles() {
  collapseScopes().forEach(([, container, button]) => {
    if (!container || !button) return;
    const blocks = qa(':scope > [data-collapse]', container);
    button.disabled = !blocks.length;
    button.textContent = blocks.some((block) => !block.classList.contains('is-collapsed')) || !blocks.length
      ? 'Свернуть все'
      : 'Развернуть все';
  });
}

export function renderSchools() {
  const query = ($('schoolSearch').value || '').trim().toLowerCase();
  const list = S.schools.filter((school) => {
    if (!query) return true;
    if (school.name.toLowerCase().includes(query)) return true;
    return (school.classes || []).some((item) => item.name.toLowerCase().includes(query));
  });
  const classes = S.schools.reduce((sum, school) => sum + (school.classes || []).length, 0);
  const contacts = S.schools.reduce(
    (sum, school) => sum + (school.classes || []).reduce((part, item) => part + (item.contacts || []).length, 0),
    0,
  );
  $('schoolsInfo').textContent = S.schools.length
    ? `Школ: ${S.schools.length} · классов: ${classes} · контактов: ${contacts}${query ? ` · найдено школ: ${list.length}` : ''}`
    : 'Пока нет ни одной школы. Добавьте школу и класс или импортируйте таблицу.';

  $('schoolList').innerHTML = list.length
    ? list.map((school) => {
      const key = schoolKey(school.id);
      const collapsed = !query && S.collapsed.has(key);
      return `
      <div class="card school-card collapse-block${collapsed ? ' is-collapsed' : ''}" data-collapse="${key}">
        <div class="card-head collapse-head">
          <button type="button" class="collapse-toggle" data-action="collapse-toggle" data-collapse-key="${key}"
                  aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="schoolBody${school.id}"
                  title="Свернуть или развернуть школу"></button>
          <button type="button" class="school-name" data-action="collapse-toggle" data-collapse-key="${key}"
                  aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="schoolBody${school.id}"
                  title="Свернуть или развернуть школу">${esc(school.name)}</button>
          <span class="badge">${(school.classes || []).length} ${plural((school.classes || []).length, 'класс', 'класса', 'классов')}</span>
          <span class="badge ok">КР: ${contactCount(school, 'KR')}</span>
          <span class="badge">РК: ${contactCount(school, 'RK')}</span>
          <span class="spacer"></span>
          <button type="button" class="btn small ghost" data-action="school-add-class" data-id="${school.id}">Добавить класс</button>
          <button type="button" class="btn small ghost" data-action="school-rename" data-id="${school.id}">Переименовать</button>
          <button type="button" class="btn small danger" data-action="school-delete" data-id="${school.id}">Удалить</button>
        </div>
        <div class="collapse-body" id="schoolBody${school.id}"${collapsed ? ' hidden' : ''}>
          ${schoolClassList(school, Boolean(query))}
        </div>
      </div>`;
    }).join('')
    : `<div class="empty">${query ? 'По запросу ничего не найдено.' : 'Школ пока нет.'}
         <div><button type="button" class="btn primary" data-action="school-create">Добавить школу и класс</button></div>
       </div>`;
  updateCollapseToggles();
}

export function schoolClassList(school, expandAll) {
  const classes = school.classes || [];
  if (!classes.length) return '<p class="muted">Классов пока нет. Добавьте первый класс.</p>';
  return classes.map((item) => {
    const key = classKey(item.id);
    const collapsed = !expandAll && S.collapsed.has(key);
    return `
    <div class="class-block collapse-block${collapsed ? ' is-collapsed' : ''}" data-collapse="${key}">
      <div class="card-head collapse-head">
        <button type="button" class="collapse-toggle" data-action="collapse-toggle" data-collapse-key="${key}"
                aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="classBody${item.id}"
                title="Свернуть или развернуть класс"></button>
        <button type="button" class="class-name" data-action="collapse-toggle" data-collapse-key="${key}"
                aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="classBody${item.id}"
                title="Свернуть или развернуть класс">${esc(item.name)}</button>
        <span class="badge mute">${(item.contacts || []).length} ${plural((item.contacts || []).length, 'контакт', 'контакта', 'контактов')}</span>
        <span class="spacer"></span>
        <button type="button" class="btn small ghost" data-action="class-rename" data-id="${item.id}">Переименовать</button>
        <button type="button" class="btn small danger" data-action="class-delete" data-id="${item.id}">Удалить</button>
      </div>
      <div class="collapse-body" id="classBody${item.id}"${collapsed ? ' hidden' : ''}>
        <div class="table-wrap table-flat">
          <table>
            <thead><tr><th>Роль</th><th>ФИО</th><th>Телефон</th><th>Действия</th></tr></thead>
            <tbody>
              ${(item.contacts || []).length ? (item.contacts || []).map((contact) => `
                <tr>
                  <td><span class="badge ${contact.role === 'KR' ? 'ok' : 'mute'}">${contact.role === 'KR' ? 'КР' : 'РК'}</span></td>
                  <td>${esc(contact.name)}${contact.opted_out ? ' <span class="badge err">отписался</span>' : ''}</td>
                  <td>${contact.phone ? `<button type="button" class="btn link" data-action="copy" data-copy="${esc(contact.phone)}">${esc(contact.phone)}</button>` : '—'}</td>
                  <td>
                    <button type="button" class="btn small ghost" data-action="contact-edit" data-id="${contact.id}">Изменить</button>
                    <button type="button" class="btn small danger" data-action="contact-delete" data-id="${contact.id}">Удалить</button>
                  </td>
                </tr>`).join('') : '<tr><td colspan="4" class="empty">Контактов нет</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>`;
  }).join('');
}

export async function createSchoolAndClass() {
  const values = await promptAction('Новая школа и класс', [
    { id: 'school', label: 'Название школы', required: true, placeholder: 'Например: Школа №12', hint: 'Если школа уже существует, укажите её точное название — будет создан только класс.' },
    { id: 'klass', label: 'Класс', required: true, placeholder: 'Например: 5А' },
  ], 'Создать');
  if (values === null) return;
  await api('/classes', { method: 'POST', body: JSON.stringify({ school_name: values.school, class_name: values.klass }) });
  await loadSchools();
  toast('Школа и класс сохранены');
}

export async function addClassToSchool(id) {
  const school = S.schools.find((item) => item.id === Number(id));
  if (!school) return;
  const values = await promptAction(`Новый класс — ${school.name}`, [
    { id: 'klass', label: 'Класс', required: true, placeholder: 'Например: 7Б' },
  ], 'Создать класс');
  if (values === null) return;
  await api('/classes', { method: 'POST', body: JSON.stringify({ school_name: school.name, class_name: values.klass }) });
  await loadSchools();
  toast('Класс добавлен');
}

export async function renameSchool(id) {
  const school = S.schools.find((item) => item.id === Number(id));
  if (!school) return;
  const values = await promptAction('Переименовать школу', [
    { id: 'name', label: 'Новое название', required: true, value: school.name },
  ]);
  if (values === null) return;
  await api(`/schools/${school.id}`, { method: 'PATCH', body: JSON.stringify({ name: values.name }) });
  await loadSchools();
  toast('Школа переименована');
}

export async function deleteSchool(id) {
  const school = S.schools.find((item) => item.id === Number(id));
  if (!school) return;
  const contacts = (school.classes || []).reduce((sum, item) => sum + (item.contacts || []).length, 0);
  const accepted = await confirmAction(
    'Удалить школу',
    `Школа «${school.name}» будет удалена вместе с ${contacts} ${plural(contacts, 'контактом', 'контактами', 'контактами')} и их заданиями в рассылках. Действие необратимо.`,
    { confirmText: 'Удалить школу' },
  );
  if (!accepted) return;
  await api(`/schools/${school.id}`, { method: 'DELETE' });
  await loadSchools();
  toast('Школа удалена');
}

export function findClass(classId) {
  for (const school of S.schools) {
    const found = (school.classes || []).find((item) => item.id === Number(classId));
    if (found) return { school, item: found };
  }
  return null;
}

export async function renameClass(id) {
  const found = findClass(id);
  if (!found) return;
  const values = await promptAction(`Переименовать класс — ${found.school.name}`, [
    { id: 'name', label: 'Новое название класса', required: true, value: found.item.name },
  ]);
  if (values === null) return;
  await api(`/classes/${found.item.id}`, { method: 'PATCH', body: JSON.stringify({ name: values.name }) });
  await loadSchools();
  toast('Класс переименован');
}

export async function deleteClass(id) {
  const found = findClass(id);
  if (!found) return;
  const count = (found.item.contacts || []).length;
  const accepted = await confirmAction(
    'Удалить класс',
    `Класс «${found.item.name}» (${found.school.name}) и ${count} ${plural(count, 'контакт', 'контакта', 'контактов')} будут удалены вместе с заданиями рассылок.`,
    { confirmText: 'Удалить класс' },
  );
  if (!accepted) return;
  await api(`/classes/${found.item.id}`, { method: 'DELETE' });
  await loadSchools();
  toast('Класс удалён');
}
