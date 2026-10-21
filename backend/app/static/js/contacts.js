/* Раздел «Контакты КР/РК». */
import { $, api, esc, plural, qa, S } from './core.js';
import { loadSchools, updateNavCounts } from './schools.js';
import { confirmAction, openModal, toast } from './ui.js';

// --- Контакты ---------------------------------------------------------------

export function contactFormFields(contact) {
  return [
    { id: 'name', label: 'ФИО', required: true, value: contact ? contact.name : '', placeholder: 'Иванова Мария Петровна' },
    { id: 'role', label: 'Роль', type: 'select', value: contact ? contact.role : 'KR', options: [{ value: 'KR', label: 'КР — классный руководитель' }, { value: 'RK', label: 'РК — родительский комитет' }] },
    { id: 'phone', label: 'Телефон для поиска в MAX', value: contact ? contact.phone || '' : '', placeholder: '+7 999 123-45-67', hint: 'Телефон обязателен для подготовки сообщения в MAX.' },
    { id: 'school', label: 'Школа', type: 'select', value: contact ? String(contact.school_id || '') : '', options: S.schools.map((school) => ({ value: String(school.id), label: school.name })) },
    { id: 'klass', label: 'Класс', type: 'select', value: contact ? String(contact.class_id || '') : '', options: [] },
    { id: 'username', label: 'Имя пользователя MAX', value: contact ? contact.username || '' : '', placeholder: '@username' },
    { id: 'chat_link', label: 'Ссылка на чат MAX', value: contact ? contact.chat_link || '' : '', placeholder: 'https://max.ru/...' },
    { id: 'consent', label: 'Основание согласия', value: contact ? contact.consent_basis || '' : '', placeholder: 'Например: согласие школы от 01.09.2026' },
  ];
}

export function fillClassSelect(preserve) {
  const school = S.schools.find((item) => item.id === Number($('field-school').value));
  const classSelect = $('field-klass');
  const wanted = preserve ? classSelect.value : '';
  classSelect.innerHTML = (school ? school.classes || [] : [])
    .map((item) => `<option value="${item.id}">${esc(item.name)}</option>`)
    .join('');
  if (wanted && Array.from(classSelect.options).some((option) => option.value === wanted)) {
    classSelect.value = wanted;
  }
}

export function contactFieldMarkup(field) {
  const control = field.type === 'select'
    ? `<select id="field-${field.id}">${(field.options || []).map((option) => `<option value="${esc(option.value)}" ${String(option.value) === String(field.value) ? 'selected' : ''}>${esc(option.label)}</option>`).join('')}</select>`
    : `<input id="field-${field.id}" value="${esc(field.value)}" placeholder="${esc(field.placeholder || '')}">`;
  return `
    <div class="field" style="margin-bottom:10px">
      <span>${esc(field.label)}${field.required ? ' <span class="req">*</span>' : ''}</span>
      ${control}
      ${field.hint ? `<small class="muted">${esc(field.hint)}</small>` : ''}
    </div>`;
}

export function readContactForm(contact) {
  const name = ($('field-name').value || '').trim();
  if (!name) {
    toast('Укажите ФИО', 'warn');
    return null;
  }
  const schoolId = Number($('field-school').value);
  const classId = Number($('field-klass').value);
  if (!schoolId) {
    toast('Выберите школу', 'warn');
    return null;
  }
  if (!classId) {
    toast('В выбранной школе нет классов — сначала создайте класс', 'warn');
    return null;
  }
  const rawPhone = ($('field-phone').value || '').trim();
  if (rawPhone && rawPhone.replace(/\D/g, '').length < 10) {
    toast('Телефон должен содержать не менее 10 цифр', 'warn');
    return null;
  }
  const customRaw = ($('field-custom-json').value || '').trim();
  let custom = {};
  if (customRaw) {
    try {
      custom = JSON.parse(customRaw);
    } catch (error) {
      toast('Дополнительные поля должны быть корректным JSON', 'warn');
      return null;
    }
  }
  return {
    name,
    role: $('field-role').value,
    phone: rawPhone || null,
    school_id: schoolId,
    class_id: classId,
    username: ($('field-username').value || '').trim() || null,
    chat_link: ($('field-chat_link').value || '').trim() || null,
    consent_basis: ($('field-consent').value || '').trim() || null,
    opted_out: Boolean($('field-optout').checked),
    custom_fields: custom,
  };
}

export async function openContactDialog(contactId) {
  if (!S.schools.length) await loadSchools();
  if (!S.contacts.length) S.contacts = await api('/clients');
  const contact = contactId ? S.contacts.find((item) => item.id === Number(contactId)) : null;
  if (contactId && !contact) {
    toast('Контакт не найден — обновите список', 'error');
    return;
  }
  const fields = contactFormFields(contact);
  const schoolField = fields.find((field) => field.id === 'school');
  if (!contact && !schoolField.value && S.schools.length) schoolField.value = String(S.schools[0].id);
  const customJson = contact && contact.custom_fields && Object.keys(contact.custom_fields).length
    ? JSON.stringify(contact.custom_fields, null, 2)
    : '';
  const body = fields.map(contactFieldMarkup).join('') + `
    <label class="check" style="margin-bottom:10px">
      <input type="checkbox" id="field-optout" ${contact && contact.opted_out ? 'checked' : ''}>
      Контакт отписался — исключать из рассылок
    </label>
    <details>
      <summary class="muted">Дополнительные поля (JSON, необязательно)</summary>
      <textarea id="field-custom-json" placeholder='{"класс_руководитель": "да"}'>${esc(customJson)}</textarea>
    </details>`;
  openModal({
    title: contact ? 'Изменить контакт' : 'Новый контакт',
    body,
    confirmText: contact ? 'Сохранить' : 'Создать',
    onReady: () => {
      fillClassSelect(false);
      $('field-school').addEventListener('change', () => fillClassSelect(false));
    },
    onSubmit: async () => {
      const payload = readContactForm(contact);
      if (!payload) return false;
      if (contact) {
        await api(`/clients/${contact.id}`, { method: 'PATCH', body: JSON.stringify(payload) });
        toast('Контакт обновлён');
      } else {
        await api('/clients', { method: 'POST', body: JSON.stringify(payload) });
        toast('Контакт создан');
      }
      await loadSchools();
      await loadContacts();
      return true;
    },
  });
}

export async function deleteContactById(id) {
  const contact = S.contacts.find((item) => item.id === Number(id));
  const accepted = await confirmAction(
    'Удалить контакт',
    contact
      ? `Контакт «${contact.name}» и все его задания в рассылках будут удалены.`
      : 'Контакт и все его задания в рассылках будут удалены.',
    { confirmText: 'Удалить' },
  );
  if (!accepted) return;
  await api(`/clients/${id}`, { method: 'DELETE' });
  S.contactsUi.selected.delete(Number(id));
  await loadSchools();
  await loadContacts();
  toast('Контакт удалён');
}

export async function loadContacts() {
  const ui = S.contactsUi;
  const params = [];
  if (ui.q) params.push(['q', ui.q]);
  if (ui.school) params.push(['school_id', ui.school]);
  if (ui.klass) params.push(['class_id', ui.klass]);
  if (ui.optedOut) params.push(['opted_out', ui.optedOut]);
  const query = params.length ? '?' + params.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&') : '';
  const rows = await api('/clients' + query);
  const existing = new Set(rows.map((item) => item.id));
  Array.from(ui.selected).forEach((id) => { if (!existing.has(id)) ui.selected.delete(id); });
  S.contacts = rows;
  renderContacts();
  updateNavCounts();
  return rows;
}

export function filteredContacts() {
  const ui = S.contactsUi;
  return S.contacts.filter((contact) => (ui.role ? contact.role === ui.role : true));
}

export function schoolNameById(id) {
  return (S.schools.find((school) => school.id === id) || {}).name || '—';
}

export function classNameById(id) {
  for (const school of S.schools) {
    const found = (school.classes || []).find((item) => item.id === id);
    if (found) return found.name;
  }
  return '—';
}

export function renderContacts() {
  const ui = S.contactsUi;
  const rows = filteredContacts();
  const pageSize = ui.pageSize;
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (ui.page > pages) ui.page = pages;
  const start = (ui.page - 1) * pageSize;
  const visible = rows.slice(start, start + pageSize);

  $('contactsInfo').textContent = rows.length
    ? `Найдено контактов: ${rows.length}${ui.role ? ` (фильтр роли: ${ui.role === 'KR' ? 'КР' : 'РК'})` : ''}`
    : 'По текущим фильтрам контактов нет.';

  $('contactRows').innerHTML = visible.length
    ? visible.map((contact) => `
      <tr>
        <td><input type="checkbox" class="contact-check" data-id="${contact.id}" ${ui.selected.has(contact.id) ? 'checked' : ''} aria-label="Выбрать ${esc(contact.name)}"></td>
        <td><b>${esc(contact.name)}</b>${contact.opted_out ? ' <span class="badge err">отписался</span>' : ''}</td>
        <td><span class="badge ${contact.role === 'KR' ? 'ok' : 'mute'}">${contact.role === 'KR' ? 'КР' : 'РК'}</span></td>
        <td>${esc(schoolNameById(contact.school_id))}</td>
        <td>${esc(classNameById(contact.class_id))}</td>
        <td>${contact.phone ? `<button type="button" class="btn link" data-action="copy" data-copy="${esc(contact.phone)}">${esc(contact.phone)}</button>` : '—'}</td>
        <td>${contact.chat_link ? '<span class="badge ok">ссылка</span>' : contact.max_user_id ? '<span class="badge">id</span>' : '<span class="badge warn">нет</span>'}</td>
        <td>
          <button type="button" class="btn small ghost" data-action="contact-edit" data-id="${contact.id}">Изменить</button>
          <button type="button" class="btn small danger" data-action="contact-delete" data-id="${contact.id}">Удалить</button>
        </td>
      </tr>`).join('')
    : '<tr><td colspan="8" class="empty">Контактов нет. Добавьте контакт или импортируйте таблицу.</td></tr>';

  qa('.contact-check', $('contactRows')).forEach((input) => {
    input.addEventListener('change', () => {
      const id = Number(input.dataset.id);
      if (input.checked) ui.selected.add(id);
      else ui.selected.delete(id);
      renderContactSelection();
    });
  });
  renderContactSelection();
  $('contactPageInfo').textContent = rows.length
    ? `Показано ${start + 1}–${Math.min(start + pageSize, rows.length)} из ${rows.length}`
    : '';
  $('contactPrev').disabled = ui.page <= 1;
  $('contactNext').disabled = ui.page >= pages;
}

export function renderContactSelection() {
  const ui = S.contactsUi;
  const visibleIds = filteredContacts()
    .slice((ui.page - 1) * ui.pageSize, ui.page * ui.pageSize)
    .map((item) => item.id);
  const allChecked = visibleIds.length > 0 && visibleIds.every((id) => ui.selected.has(id));
  const header = $('selectAllContacts');
  header.checked = allChecked;
  header.indeterminate = !allChecked && visibleIds.some((id) => ui.selected.has(id));
  $('contactBulk').hidden = ui.selected.size === 0;
  $('contactSelectedCount').textContent = `Выбрано: ${ui.selected.size}`;
}

export async function deleteSelectedContacts() {
  const ids = Array.from(S.contactsUi.selected);
  if (!ids.length) return;
  const accepted = await confirmAction(
    'Удалить контакты',
    `Будет удалено ${ids.length} ${plural(ids.length, 'контакт', 'контакта', 'контактов')} вместе с их заданиями в рассылках.`,
    { confirmText: 'Удалить контакты' },
  );
  if (!accepted) return;
  const result = await api('/clients/delete', {
    method: 'POST',
    body: JSON.stringify({ client_ids: ids }),
  });
  S.contactsUi.selected.clear();
  await loadSchools();
  await loadContacts();
  toast(`Удалено контактов: ${result.deleted}`);
}

export function downloadCsv(filename, header, rows) {
  const safe = (value) => {
    const text = value === null || value === undefined ? '' : String(value);
    const guarded = /^[=+\-@]/.test(text) ? `'${text}` : text;
    return `"${guarded.replace(/"/g, '""')}"`;
  };
  const content = [header, ...rows].map((row) => row.map(safe).join(';')).join('\r\n');
  const blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function exportContacts() {
  const ui = S.contactsUi;
  const rows = ui.selected.size
    ? S.contacts.filter((contact) => ui.selected.has(contact.id))
    : filteredContacts();
  if (!rows.length) {
    toast('Нет данных для экспорта', 'warn');
    return;
  }
  downloadCsv(
    `contacts-${new Date().toISOString().slice(0, 10)}.csv`,
    ['ФИО', 'Роль', 'Школа', 'Класс', 'Телефон', 'MAX user id', 'Ссылка', 'Отписался', 'Согласие'],
    rows.map((contact) => [
      contact.name,
      contact.role,
      schoolNameById(contact.school_id),
      classNameById(contact.class_id),
      contact.phone || '',
      contact.max_user_id || '',
      contact.chat_link || '',
      contact.opted_out ? 'да' : 'нет',
      contact.consent_basis || '',
    ]),
  );
  toast(`Экспортировано контактов: ${rows.length}`);
}

export async function copyToClipboard(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const helper = document.createElement('textarea');
      helper.value = text;
      helper.setAttribute('readonly', 'readonly');
      helper.style.position = 'fixed';
      helper.style.opacity = '0';
      document.body.appendChild(helper);
      helper.select();
      document.execCommand('copy');
      helper.remove();
    }
    toast('Скопировано в буфер обмена');
  } catch (error) {
    toast('Не удалось скопировать: ' + error.message, 'error');
  }
}
