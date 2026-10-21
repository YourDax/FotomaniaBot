/* Рассылки: выбор получателей, создание, список, тексты сообщений. */
import { schoolNameById } from './contacts.js';
import { $, api, DONE_STATUSES, EDITABLE_TASK_STATUSES, esc, fmtDateTime, plural, qa, S, statusName } from './core.js';
import { renderDashboard } from './dashboard.js';
import { go } from './router.js';
import { loadSchools, schoolKey, updateCollapseToggles, updateNavCounts } from './schools.js';
import { refreshTasks } from './tasks.js';
import { confirmAction, openModal, promptAction, toast } from './ui.js';

// --- Рассылки: выбор получателей и создание --------------------------------

export function pickerContacts() {
  const query = ($('recipientSearch').value || '').trim().toLowerCase();
  const result = [];
  S.schools.forEach((school) => {
    (school.classes || []).forEach((item) => {
      (item.contacts || []).forEach((contact) => {
        const haystack = `${contact.name} ${school.name} ${item.name} ${contact.phone || ''}`.toLowerCase();
        if (query && !haystack.includes(query)) return;
        result.push({ ...contact, school_id: school.id, class_id: item.id, school: school.name, klass: item.name });
      });
    });
  });
  return result;
}

export function renderPicker() {
  const rows = pickerContacts();
  if (!S.schools.length) {
    $('campaignPicker').innerHTML = '<p class="muted pad-10">Школ пока нет. Добавьте школу и контакты на вкладке «Школы и классы» или импортируйте таблицу.</p>';
    updateCollapseToggles();
    return;
  }
  const grouped = new Map();
  rows.forEach((row) => {
    if (!grouped.has(row.school_id)) grouped.set(row.school_id, new Map());
    const classes = grouped.get(row.school_id);
    if (!classes.has(row.class_id)) classes.set(row.class_id, []);
    classes.get(row.class_id).push(row);
  });
  if (!grouped.size) {
    $('campaignPicker').innerHTML = '<p class="muted pad-10">По запросу получатели не найдены.</p>';
    updateCollapseToggles();
    return;
  }
  const query = ($('recipientSearch').value || '').trim().toLowerCase();
  $('campaignPicker').innerHTML = Array.from(grouped.entries()).map(([schoolId, classes]) => {
    const school = S.schools.find((item) => item.id === schoolId);
    const schoolContactIds = Array.from(classes.values()).flat().map((contact) => contact.id);
    const selectedCount = schoolContactIds.filter((id) => S.recipients.selected.has(id)).length;
    const allSelected = schoolContactIds.length > 0 && selectedCount === schoolContactIds.length;
    const key = schoolKey(schoolId);
    const collapsed = !query && S.collapsed.has(key);
    return `
      <div class="group collapse-block${collapsed ? ' is-collapsed' : ''}" data-collapse="${key}">
        <div class="group-head">
          <button type="button" class="collapse-toggle" data-action="collapse-toggle" data-collapse-key="${key}"
                  aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="pickBody${schoolId}"
                  title="Свернуть или развернуть школу"></button>
          <input type="checkbox" data-pick-school="${schoolId}" ${allSelected ? 'checked' : ''} aria-label="Выбрать школу ${esc(school ? school.name : '')}">
          <button type="button" class="group-name" data-action="collapse-toggle" data-collapse-key="${key}"
                  aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="pickBody${schoolId}"
                  title="Свернуть или развернуть школу">${esc(school ? school.name : 'Школа ' + schoolId)}</button>
          <span class="muted">${schoolContactIds.length} ${plural(schoolContactIds.length, 'получатель', 'получателя', 'получателей')}</span>
          ${selectedCount ? `<span class="badge ok">выбрано: ${selectedCount}</span>` : ''}
        </div>
        <div class="class-list collapse-body" id="pickBody${schoolId}"${collapsed ? ' hidden' : ''}>
          ${Array.from(classes.entries()).map(([classId, contacts]) => `
            <div>
              <div class="muted my-4">${esc(contacts[0].klass || 'без класса')}</div>
              ${contacts.map((contact) => `
                <label class="item">
                  <input type="checkbox" data-pick-contact="${contact.id}" ${S.recipients.selected.has(contact.id) ? 'checked' : ''} ${contact.opted_out ? 'disabled' : ''}>
                  <span>${esc(contact.name)} <small>${contact.role === 'KR' ? 'КР' : 'РК'}${contact.phone ? ' · ' + esc(contact.phone) : ''}</small></span>
                  ${contact.opted_out ? '<span class="badge err">отписался</span>' : ''}
                </label>`).join('')}
            </div>`).join('')}
        </div>
      </div>`;
  }).join('');

  updateCollapseToggles();
  qa('[data-pick-contact]', $('campaignPicker')).forEach((input) => {
    input.addEventListener('change', () => {
      const id = Number(input.dataset.pickContact);
      if (input.checked) S.recipients.selected.add(id);
      else S.recipients.selected.delete(id);
      renderPickerSelection();
    });
  });
  qa('[data-pick-school]', $('campaignPicker')).forEach((input) => {
    input.addEventListener('change', () => {
      const schoolId = Number(input.dataset.pickSchool);
      pickerContacts().forEach((contact) => {
        if (contact.school_id !== schoolId || contact.opted_out) return;
        if (input.checked) S.recipients.selected.add(contact.id);
        else S.recipients.selected.delete(contact.id);
      });
      renderPicker();
    });
  });
  renderPickerSelection();
}

export function recipientStats() {
  const all = [];
  S.schools.forEach((school) => (school.classes || []).forEach((item) => (item.contacts || [])
    .forEach((contact) => all.push({ ...contact, school_id: school.id }))));
  const chosen = all.filter((contact) => S.recipients.selected.has(contact.id));
  return {
    total: chosen.length,
    kr: chosen.filter((contact) => contact.role === 'KR').length,
    rk: chosen.filter((contact) => contact.role === 'RK').length,
    skipped: all.filter((contact) => contact.opted_out && S.recipients.selected.has(contact.id)).length,
    all,
  };
}

export function renderPickerSelection() {
  const stats = recipientStats();
  $('campaignSelected').textContent = `Выбрано получателей: ${stats.total}`;
  $('campaignSelectedBreakdown').textContent = stats.total
    ? `КР: ${stats.kr} · РК: ${stats.rk}${stats.skipped ? ` · отписавшихся: ${stats.skipped}` : ''}`
    : 'Отметьте получателей или используйте «Выбрать всех»';
}

export function renderCampaignSelection() {
  renderPickerSelection();
}

export function previewCampaign() {
  const stats = recipientStats();
  if (!stats.total) {
    toast('Сначала выберите получателей', 'warn');
    return;
  }
  const kr = S.messageSets.KR.read();
  const rk = S.messageSets.RK.read();
  const problem = kr.error || rk.error;
  if (problem) {
    toast(problem, 'warn');
    return;
  }
  const first = stats.all.find((contact) => S.recipients.selected.has(contact.id));
  const own = first.role === 'RK' ? rk.values : kr.values;
  const templates = own.length ? own : (first.role === 'RK' ? kr.values : rk.values);
  if (!templates.length) {
    toast('Заполните текст для КР или РК', 'warn');
    return;
  }
  const rendered = templates
    .map((template, index) => {
      const text = template.split('{name}').join(first.name);
      return templates.length > 1 ? `— Сообщение ${index + 1} из ${templates.length} —\n${text}` : text;
    })
    .join('\n\n');
  $('campaignPreview').textContent = `Кому: ${first.name} (${ROLE_LABEL[first.role] || first.role})\n\n${rendered}`;
}

// --- Форма новой рассылки: три шага ------------------------------------------

const CAMPAIGN_STEPS = 3;

export function openCampaignForm() {
  $('campaignForm').classList.remove('hidden');
  setCampaignStep(1, { force: true });
  $('campaignForm').scrollIntoView({ behavior: 'smooth', block: 'start' });
  $('campaignName').focus({ preventScroll: true });
}

export function closeCampaignForm() {
  $('campaignForm').classList.add('hidden');
  $('campaignName').value = '';
  $('campaignDescription').value = '';
  S.messageSets.KR.reset();
  S.messageSets.RK.reset();
  S.recipients.selected.clear();
  renderPicker();
}

// Возвращает текст проблемы на шаге или null, если шаг заполнен корректно.
export function stepProblem(step) {
  if (step === 1) {
    if (!($('campaignName').value || '').trim()) return 'Укажите название рассылки';
    const kr = S.messageSets.KR.read();
    const rk = S.messageSets.RK.read();
    if (kr.error || rk.error) return kr.error || rk.error;
    if (!kr.values.length && !rk.values.length) return 'Заполните текст хотя бы для одной роли';
  }
  if (step === 2 && !recipientStats().total) return 'Выберите хотя бы одного получателя';
  return null;
}

export function setCampaignStep(target, { force = false } = {}) {
  const wanted = Math.min(CAMPAIGN_STEPS, Math.max(1, target));
  if (!force) {
    // Вперёд можно только через заполненные шаги; назад — всегда.
    for (let step = S.campaignsUi.formStep; step < wanted; step += 1) {
      const problem = stepProblem(step);
      if (problem) {
        toast(problem, 'warn');
        return;
      }
    }
  }
  S.campaignsUi.formStep = wanted;
  qa('[data-cpanel]', $('campaignForm')).forEach((panel) => {
    panel.hidden = Number(panel.dataset.cpanel) !== wanted;
  });
  qa('[data-cstep]', $('campaignStepper')).forEach((button) => {
    const number = Number(button.dataset.cstep);
    button.classList.toggle('active', number === wanted);
    button.classList.toggle('done', number < wanted);
    if (number === wanted) button.setAttribute('aria-current', 'step');
    else button.removeAttribute('aria-current');
  });
  if (wanted === 3) renderCampaignSummary();
}

export function renderCampaignSummary() {
  const stats = recipientStats();
  const kr = S.messageSets.KR.read().values.length;
  const rk = S.messageSets.RK.read().values.length;
  const schools = new Set(stats.all.filter((contact) => S.recipients.selected.has(contact.id)).map((contact) => contact.school_id));
  $('campaignSummary').innerHTML = `
    <dt>Название</dt><dd>${esc(($('campaignName').value || '').trim())}</dd>
    <dt>Сообщения</dt><dd>КР: ${kr || 'нет'} · РК: ${rk || 'нет'}</dd>
    <dt>Получатели</dt><dd>${stats.total} (КР: ${stats.kr} · РК: ${stats.rk}${stats.skipped ? ` · отписавшихся: ${stats.skipped}` : ''})</dd>
    <dt>Школ</dt><dd>${schools.size}</dd>`;
  previewCampaign();
}

// Новая рассылка на основе существующей: те же тексты и получатели (кроме удалённых и отписавшихся).
export async function duplicateCampaign(id) {
  const campaign = S.campaigns.find((item) => item.id === Number(id));
  if (!campaign) return;
  const tasks = await api(`/campaigns/${campaign.id}/tasks`);
  if (!S.schools.length) await loadSchools();
  const available = new Set(recipientStats().all.filter((contact) => !contact.opted_out).map((contact) => contact.id));
  const ids = tasks.map((task) => task.client_id).filter((clientId) => available.has(clientId));
  go('campaigns');
  $('campaignName').value = `Копия — ${campaign.name}`.slice(0, 200);
  $('campaignDescription').value = campaign.description || '';
  S.messageSets.KR.set(campaign.messages_kr);
  S.messageSets.RK.set(campaign.messages_rk);
  S.recipients.selected = new Set(ids);
  renderPicker();
  openCampaignForm();
  const lost = tasks.length - ids.length;
  toast(`Форма заполнена из рассылки «${campaign.name}». Получателей: ${ids.length}` +
    (lost ? `, пропущено (удалены или отписались): ${lost}` : ''), lost ? 'warn' : 'ok');
}

// --- Рассылки: список, создание, действия -----------------------------------

export function campaignProgress(campaign) {
  const counts = campaign.status_counts || {};
  const total = campaign.task_count || 0;
  const done = DONE_STATUSES.reduce((sum, code) => sum + (counts[code] || 0), 0);
  const review = (counts.REQUIRES_REVIEW || 0) + (counts.PENDING || 0) + (counts.PROCESSING || 0);
  const percent = total ? Math.round((done / total) * 100) : 0;
  return { total, done, review, percent, counts };
}

export function campaignProgressCell(campaign) {
  const stats = campaignProgress(campaign);
  const tone = stats.percent === 100 ? 'ok' : stats.counts.FAILED ? 'err' : '';
  return `
    <div class="row gap-8">
      <div class="grow minw-110">
        <div class="progress ${tone}"><span style="width:${stats.percent}%"></span></div>
      </div>
      <span class="muted">${stats.done} / ${stats.total}</span>
    </div>
    <span class="muted">${stats.review ? `Ждут оператора: ${stats.review}` : stats.total ? 'Все задания обработаны' : 'Заданий нет'}</span>`;
}

export async function loadCampaigns() {
  S.campaigns = await api('/campaigns');
  const available = new Set(S.campaigns.map((item) => item.id));
  Array.from(S.campaignsUi.selected).forEach((id) => {
    if (!available.has(id)) S.campaignsUi.selected.delete(id);
  });
  renderCampaigns();
  renderRecentCampaigns();
  renderDashboard();
  updateNavCounts();
  return S.campaigns;
}

export function filteredCampaigns() {
  const ui = S.campaignsUi;
  const query = ui.q.trim().toLowerCase();
  return S.campaigns.filter((campaign) => {
    if (ui.status && campaign.status !== ui.status) return false;
    if (query && !campaign.name.toLowerCase().includes(query)) return false;
    return true;
  });
}

export function renderCampaigns() {
  const ui = S.campaignsUi;
  const rows = filteredCampaigns();
  const pages = Math.max(1, Math.ceil(rows.length / ui.pageSize));
  if (ui.page > pages) ui.page = pages;
  const start = (ui.page - 1) * ui.pageSize;
  const visible = rows.slice(start, start + ui.pageSize);

  $('campaignRows').innerHTML = visible.length
    ? visible.map((campaign) => `
      <tr>
        <td data-label=""><input type="checkbox" class="campaign-check" data-id="${campaign.id}" ${ui.selected.has(campaign.id) ? 'checked' : ''} aria-label="Выбрать рассылку"></td>
        <td data-label="Рассылка">
          <b>${esc(campaign.name)}</b>
          ${campaign.description ? `<span class="muted">${esc(campaign.description)}</span>` : ''}
          <span class="badge ${campaign.status === 'COMPLETED' ? 'ok' : campaign.status === 'STOPPED' ? 'err' : 'mute'}">${esc(statusName(campaign.status))}</span>
        </td>
        <td data-label="Школа">${campaign.school_id ? esc(schoolNameById(campaign.school_id)) : '<span class="muted">все школы</span>'}</td>
        <td data-label="Создана">${esc(fmtDateTime(campaign.created_at))}</td>
        <td data-label="Прогресс">${campaignProgressCell(campaign)}</td>
        <td data-label="Действия">
          <div class="row gap-6">
            <button type="button" class="btn small ghost" data-action="campaign-open" data-id="${campaign.id}">Задания</button>
            ${campaign.status === 'DRAFT' ? `<button type="button" class="btn small primary" data-action="campaign-start" data-id="${campaign.id}">Запустить</button>` : ''}
            ${['RUNNING', 'WAITING_REVIEW'].includes(campaign.status) ? `<button type="button" class="btn small ghost" data-action="campaign-stop" data-id="${campaign.id}">Остановить</button>` : ''}
            <button type="button" class="btn small ghost" data-action="campaign-duplicate" data-id="${campaign.id}" title="Создать новую рассылку с теми же текстами и получателями">Дублировать</button>
            <button type="button" class="btn small ghost" data-action="campaign-export" data-id="${campaign.id}">CSV</button>
            <button type="button" class="btn small danger" data-action="campaign-delete" data-id="${campaign.id}">Удалить</button>
          </div>
        </td>
      </tr>`).join('')
    : '<tr><td colspan="6" class="empty">Рассылок пока нет. Нажмите «Новая рассылка», чтобы создать первую.</td></tr>';

  qa('.campaign-check', $('campaignRows')).forEach((input) => {
    input.addEventListener('change', () => {
      const id = Number(input.dataset.id);
      if (input.checked) ui.selected.add(id);
      else ui.selected.delete(id);
      renderCampaignSelection();
    });
  });

  const visibleIds = visible.map((item) => item.id);
  const allChecked = visibleIds.length > 0 && visibleIds.every((id) => ui.selected.has(id));
  const header = $('selectAllCampaigns');
  header.checked = allChecked;
  header.indeterminate = !allChecked && visibleIds.some((id) => ui.selected.has(id));
  $('campaignBulk').hidden = ui.selected.size === 0;
  $('campaignSelectedCount').textContent = `Выбрано: ${ui.selected.size}`;
  $('campaignPageInfo').textContent = rows.length
    ? `Показано ${start + 1}–${Math.min(start + ui.pageSize, rows.length)} из ${rows.length}`
    : '';
  $('campaignPrev').disabled = ui.page <= 1;
  $('campaignNext').disabled = ui.page >= pages;
}

export function renderRecentCampaigns() {
  const recent = S.campaigns.slice(0, 5);
  $('recentCampaigns').innerHTML = recent.length
    ? `<div class="table-wrap table-flat">
         <table>
           <thead><tr><th>Рассылка</th><th>Статус</th><th>Прогресс</th><th></th></tr></thead>
           <tbody>${recent.map((campaign) => `
             <tr>
               <td><b>${esc(campaign.name)}</b><span class="muted">${esc(fmtDateTime(campaign.created_at))}</span></td>
               <td><span class="badge ${campaign.status === 'COMPLETED' ? 'ok' : campaign.status === 'STOPPED' ? 'err' : 'mute'}">${esc(statusName(campaign.status))}</span></td>
               <td>${campaignProgressCell(campaign)}</td>
               <td><button type="button" class="btn small ghost" data-action="campaign-open" data-id="${campaign.id}">Открыть</button></td>
             </tr>`).join('')}</tbody>
         </table>
       </div>`
    : '<p class="muted">Рассылок пока нет. Создайте первую — она появится здесь и в разделе «Рассылки».</p>';
}

export async function createCampaign() {
  const name = ($('campaignName').value || '').trim();
  const kr = S.messageSets.KR.read();
  const rk = S.messageSets.RK.read();
  const stats = recipientStats();
  if (!name) {
    toast('Укажите название рассылки', 'warn');
    $('campaignName').focus();
    return;
  }
  if (!stats.total) {
    toast('Выберите хотя бы одного получателя', 'warn');
    return;
  }
  if (kr.error || rk.error) {
    toast(kr.error || rk.error, 'warn');
    return;
  }
  if (!kr.values.length && !rk.values.length) {
    toast('Заполните текст хотя бы для одной роли', 'warn');
    return;
  }
  const button = $('campaignCreateBtn');
  button.setAttribute('aria-busy', 'true');
  button.disabled = true;
  try {
    const schoolIds = new Set(stats.all
      .filter((contact) => S.recipients.selected.has(contact.id))
      .map((contact) => contact.school_id));
    const created = await api('/campaigns', {
      method: 'POST',
      body: JSON.stringify({
        name,
        description: ($('campaignDescription').value || '').trim(),
        message: kr.values[0] || rk.values[0],
        messages_kr: kr.values,
        messages_rk: rk.values,
        client_ids: Array.from(S.recipients.selected),
        school_id: schoolIds.size === 1 ? Array.from(schoolIds)[0] : null,
      }),
    });
    toast(`Рассылка создана. Получателей: ${created.task_count}`);
    await loadMessageTemplates().catch(() => {});
    closeCampaignForm();
    await loadSchools();
    await loadCampaigns();
    go('tasks', { campaignId: created.id });
  } finally {
    button.removeAttribute('aria-busy');
    button.disabled = false;
  }
}

export async function startCampaign(id) {
  const campaign = S.campaigns.find((item) => item.id === Number(id));
  const accepted = await confirmAction(
    'Запустить рассылку',
    `Рассылка «${campaign ? campaign.name : id}» перейдёт в работу: заданий ${campaign ? campaign.task_count : '—'} будут переведены в статус ожидания оператора. Автоматическая отправка не выполняется.`,
    { confirmText: 'Запустить', danger: false },
  );
  if (!accepted) return;
  await api(`/campaigns/${id}/start`, { method: 'POST' });
  await loadCampaigns();
  toast(`Рассылка «${campaign ? campaign.name : id}» запущена`);
}

export async function stopCampaign(id) {
  const campaign = S.campaigns.find((item) => item.id === Number(id));
  const progress = campaign ? campaignProgress(campaign) : null;
  const values = await promptAction('Остановить рассылку', [
    {
      id: 'reason',
      label: 'Причина остановки',
      value: 'Остановлено оператором',
      required: true,
      hint: progress ? `Необработанных заданий: ${progress.total - progress.done}. Отправленные задания не изменятся.` : '',
    },
  ], 'Остановить');
  if (values === null) return;
  await api(`/campaigns/${id}/stop?reason=${encodeURIComponent(values.reason)}`, { method: 'POST' });
  await loadCampaigns();
  if (S.tasksUi.campaignId === Number(id)) await refreshTasks();
  toast('Рассылка остановлена');
}

export async function deleteCampaign(id) {
  const campaign = S.campaigns.find((item) => item.id === Number(id));
  const accepted = await confirmAction(
    'Удалить рассылку',
    `Рассылка «${campaign ? campaign.name : id}» и все её задания${campaign ? ` (${campaign.task_count})` : ''} будут удалены. Действие необратимо.`,
    { confirmText: 'Удалить рассылку' },
  );
  if (!accepted) return;
  await api(`/campaigns/${id}`, { method: 'DELETE' });
  S.campaignsUi.selected.delete(Number(id));
  if (S.tasksUi.campaignId === Number(id)) {
    S.tasksUi.campaignId = null;
    go('campaigns');
  }
  await loadCampaigns();
  toast('Рассылка удалена');
}

export async function deleteSelectedCampaigns() {
  const ids = Array.from(S.campaignsUi.selected);
  if (!ids.length) return;
  const accepted = await confirmAction(
    'Удалить рассылки',
    `Будет удалено ${ids.length} ${plural(ids.length, 'рассылка', 'рассылки', 'рассылок')} вместе с заданиями.`,
    { confirmText: 'Удалить рассылки' },
  );
  if (!accepted) return;
  const result = await api('/campaigns/delete', { method: 'POST', body: JSON.stringify({ campaign_ids: ids }) });
  S.campaignsUi.selected.clear();
  await loadCampaigns();
  toast(`Удалено рассылок: ${result.deleted}`);
}

// --- Сохранённые тексты рассылок (КР и РК раздельно) ---------------------------

export const MAX_MESSAGES = 5;
export const ROLE_LABEL = { KR: 'КР', RK: 'РК' };

export const fetchMessageTemplates = (role) => api(`/message-templates/${role}`);

export async function loadMessageTemplates() {
  const [kr, rk] = await Promise.all([
    fetchMessageTemplates('KR'),
    fetchMessageTemplates('RK'),
  ]);
  S.templates = { KR: kr, RK: rk };
  Object.values(S.messageSets).forEach((set) => set.refreshTemplates());
  return S.templates;
}

export function templateOptions(role) {
  const items = (S.templates && S.templates[role]) || [];
  return '<option value="">Сохранённые тексты…</option>' + items
    .map((item) => {
      const preview = item.body.replace(/\s+/g, ' ').slice(0, 70);
      return `<option value="${item.id}">${esc(preview)}${item.body.length > 70 ? '…' : ''}</option>`;
    })
    .join('');
}

/**
 * Набор из 1–5 полей сообщений для роли. Введённые тексты хранятся в state и не
 * теряются, если уменьшить, а затем снова увеличить количество сообщений.
 */
export function createMessageSet(host, role, initial) {
  const label = ROLE_LABEL[role];
  const start = (Array.isArray(initial) && initial.length ? initial : ['']).slice(0, MAX_MESSAGES);
  const state = {
    count: start.length,
    values: Array.from({ length: MAX_MESSAGES }, (_, index) => start[index] || ''),
  };

  const fieldHtml = (index) => {
    const title = state.count > 1 ? `Сообщение ${index + 1} для ${label}` : `Текст для ${label}`;
    return `
      <div class="field msgset-item">
        <span>${title}</span>
        <textarea data-msg-text="${index}" maxlength="4000" placeholder="Здравствуйте, {name}!">${esc(state.values[index])}</textarea>
        <select data-msg-tpl="${index}" aria-label="Сохранённые тексты для сообщения ${index + 1}">${templateOptions(role)}</select>
        <small class="muted"><span data-msg-counter="${index}">${state.values[index].length}</span> / 4000 символов · доступна подстановка {name}</small>
      </div>`;
  };

  function render() {
    const counts = Array.from({ length: MAX_MESSAGES }, (_, index) => index + 1)
      .map((n) => `<option value="${n}" ${n === state.count ? 'selected' : ''}>${n}</option>`).join('');
    host.innerHTML = `
      <div class="msgset-head">
        <span class="msgset-title">Тексты для ${label}</span>
        <label class="msgset-count">Сообщений
          <select data-msg-count aria-label="Сколько сообщений подготовить для ${label}">${counts}</select>
        </label>
      </div>
      ${Array.from({ length: state.count }, (_, index) => fieldHtml(index)).join('')}`;
  }

  host.addEventListener('input', (event) => {
    const area = event.target.closest('[data-msg-text]');
    if (!area) return;
    const index = Number(area.dataset.msgText);
    state.values[index] = area.value;
    const counter = host.querySelector(`[data-msg-counter="${index}"]`);
    if (counter) counter.textContent = String(area.value.length);
  });
  host.addEventListener('change', (event) => {
    const countSelect = event.target.closest('[data-msg-count]');
    if (countSelect) {
      state.count = Math.min(MAX_MESSAGES, Math.max(1, Number(countSelect.value) || 1));
      render();
      return;
    }
    const tpl = event.target.closest('[data-msg-tpl]');
    if (!tpl) return;
    const index = Number(tpl.dataset.msgTpl);
    const item = ((S.templates && S.templates[role]) || []).find((entry) => entry.id === Number(tpl.value));
    tpl.value = '';
    if (!item) return;
    state.values[index] = item.body;
    const area = host.querySelector(`[data-msg-text="${index}"]`);
    if (area) area.value = item.body;
    const counter = host.querySelector(`[data-msg-counter="${index}"]`);
    if (counter) counter.textContent = String(item.body.length);
  });

  render();
  return {
    /** values — тексты активных полей; пусто, если все поля пусты; error — если заполнены не все. */
    read() {
      const values = state.values.slice(0, state.count).map((value) => value.trim());
      if (values.every((value) => !value)) return { values: [], error: null };
      const missing = values.findIndex((value) => !value);
      if (missing >= 0) {
        return {
          values,
          error: state.count > 1
            ? `Заполните сообщение ${missing + 1} для ${label} или уменьшите количество сообщений`
            : `Заполните текст для ${label}`,
        };
      }
      return { values, error: null };
    },
    reset() {
      state.count = 1;
      state.values = state.values.map(() => '');
      render();
    },
    set(values) {
      const next = (Array.isArray(values) && values.length ? values : ['']).slice(0, MAX_MESSAGES);
      state.count = next.length;
      state.values = Array.from({ length: MAX_MESSAGES }, (_, index) => next[index] || '');
      render();
    },
    refreshTemplates() {
      host.querySelectorAll('[data-msg-tpl]').forEach((select) => {
        select.innerHTML = templateOptions(role);
      });
    },
  };
}

export function initMessageSets() {
  S.messageSets = {
    KR: createMessageSet($('msgsetKR'), 'KR'),
    RK: createMessageSet($('msgsetRK'), 'RK'),
  };
}

// --- Редактирование текста уже созданной рассылки ----------------------------

export function openCampaignMessagesDialog() {
  const campaign = S.campaign;
  if (!campaign) return;
  const sets = {};
  openModal({
    title: 'Изменить тексты рассылки',
    body: `
      <p class="muted m-0 mb-12">Изменения применятся ко всем заданиям, которые ещё не обработаны. Отправленные, неуспешные и отменённые задания не меняются. Персональные правки отдельных получателей будут перезаписаны, а отметки «черновик готов» сохранятся только у неизменённых сообщений.</p>
      <div class="msgset mb-14" id="editSetKR"></div>
      <div class="msgset" id="editSetRK"></div>`,
    confirmText: 'Применить ко всем',
    onReady: () => {
      sets.KR = createMessageSet($('editSetKR'), 'KR', campaign.messages_kr);
      sets.RK = createMessageSet($('editSetRK'), 'RK', campaign.messages_rk);
    },
    onSubmit: async () => {
      const kr = sets.KR.read();
      const rk = sets.RK.read();
      if (kr.error || rk.error) {
        toast(kr.error || rk.error, 'warn');
        return false;
      }
      if (!kr.values.length && !rk.values.length) {
        toast('Заполните текст хотя бы для одной роли', 'warn');
        return false;
      }
      const result = await api(`/campaigns/${campaign.id}/messages`, {
        method: 'PATCH',
        body: JSON.stringify({ messages_kr: kr.values, messages_rk: rk.values }),
      });
      await loadMessageTemplates().catch(() => {});
      await refreshTasks();
      toast(`Тексты обновлены. Изменено заданий: ${result.updated}, пропущено обработанных: ${result.skipped}`);
      return true;
    },
  });
}

export function openTaskMessageDialog(taskId, messageNo = 1) {
  const task = S.tasks.find((item) => item.id === taskId);
  if (!task) return;
  const entry = (task.messages || []).find((item) => item.index === messageNo);
  if (!EDITABLE_TASK_STATUSES.includes(task.status)) {
    toast('Текст можно менять только у необработанных заданий', 'warn');
    return;
  }
  openModal({
    title: `Текст${(task.messages || []).length > 1 ? ` сообщения ${messageNo}` : ''} для ${task.client}`,
    body: `
      <p class="muted m-0 mb-10">Правка касается только этого получателя. Черновик в MAX придётся подготовить заново.</p>
      <div class="field">
        <span>Текст сообщения <span class="req">*</span></span>
        <textarea id="editTaskMessage" maxlength="4000">${esc(entry ? entry.text : (task.message || ''))}</textarea>
        <small class="muted"><span id="editTaskCounter">${(entry ? entry.text : (task.message || '')).length}</span> / 4000 символов</small>
      </div>`,
    confirmText: 'Сохранить текст',
    onReady: () => {
      $('editTaskMessage').addEventListener('input', () => {
        $('editTaskCounter').textContent = String($('editTaskMessage').value.length);
      });
    },
    onSubmit: async () => {
      const text = ($('editTaskMessage').value || '').trim();
      if (!text) {
        toast('Текст сообщения не может быть пустым', 'warn');
        return false;
      }
      await api(`/tasks/${taskId}/message`, {
        method: 'PATCH',
        body: JSON.stringify({ message: text, index: messageNo }),
      });
      toast('Текст задания обновлён');
      await refreshTasks();
      return true;
    },
  });
}
