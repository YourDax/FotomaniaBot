/* Задания рассылки: таблица, карточка, действия в MAX, автообновление. */
import { campaignProgress, loadCampaigns } from './campaigns.js';
import { $, api, BAD_STATUSES, DONE_STATUSES, EDITABLE_TASK_STATUSES, esc, fmtDateTime, fmtTime, plural, qa, S, statusName, TASK_STATUSES, TODO_FILTER } from './core.js';
import { go } from './router.js';
import { loadSchools } from './schools.js';
import { confirmAction, toast } from './ui.js';

// --- Задания рассылки -------------------------------------------------------

export async function openTasks(campaignId) {
  if (!campaignId) {
    go('campaigns');
    return;
  }
  if (S.tasksUi.campaignId !== Number(campaignId)) S.tasksUi.cursor = null; // другая рассылка: полная загрузка
  S.tasksUi.campaignId = Number(campaignId);
  S.tasksUi.page = 1;
  if (!S.schools.length) await loadSchools();
  if (!S.campaigns.length) await loadCampaigns();
  await refreshTasks();
}

export async function refreshTasks() {
  const campaignId = S.tasksUi.campaignId;
  if (!campaignId) return;
  const ui = S.tasksUi;
  // Курсор есть, пока открыта та же рассылка: тогда сервер присылает только изменения.
  const incremental = ui.cursor && ui.cursorCampaignId === campaignId && S.campaign && S.campaign.id === campaignId;
  const query = incremental ? `?since=${encodeURIComponent(ui.cursor)}` : '';
  const [campaign, delta] = await Promise.all([
    api(`/campaigns/${campaignId}`),
    api(`/campaigns/${campaignId}/tasks/changes${query}`),
  ]);
  if (campaignId !== S.tasksUi.campaignId) return; // пользователь уже открыл другую рассылку
  const byId = new Map((incremental ? S.tasks : []).map((task) => [task.id, task]));
  delta.changed.forEach((task) => byId.set(task.id, task));
  const tasks = delta.ids.map((id) => byId.get(id)).filter(Boolean);
  const idsChanged = S.tasks.length !== delta.ids.length || S.tasks.some((task, index) => task.id !== delta.ids[index]);
  const campaignChanged = JSON.stringify(campaign) !== ui.campaignSignature;
  ui.cursor = delta.cursor;
  ui.cursorCampaignId = campaignId;
  ui.campaignSignature = JSON.stringify(campaign);
  ui.updatedAt = new Date();
  $('taskLastError').textContent = 'ошибок нет';
  if (incremental && !delta.changed.length && !idsChanged && !campaignChanged) {
    $('taskUpdatedAt').textContent = fmtTime(ui.updatedAt); // ничего не менялось: таблицу не перерисовываем
    return;
  }
  S.campaign = campaign;
  S.tasks = tasks;
  if (ui.selectedId && !tasks.some((task) => task.id === ui.selectedId)) ui.selectedId = null;
  renderTasks();
}

export function taskFiltered() {
  const ui = S.tasksUi;
  const query = ui.q.trim().toLowerCase();
  let rows = S.tasks.filter((task) => {
    if (ui.statusFilter === TODO_FILTER) {
      if (DONE_STATUSES.includes(task.status)) return false;
    } else if (ui.statusFilter && task.status !== ui.statusFilter) return false;
    if (ui.role && task.recipient_role !== ui.role) return false;
    if (query) {
      const haystack = `${task.client} ${task.phone || ''} ${task.school || ''} ${task.class_name || ''}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
  if (ui.sort === 'status') rows = rows.slice().sort((a, b) => String(a.status).localeCompare(String(b.status)));
  if (ui.sort === 'name') rows = rows.slice().sort((a, b) => String(a.client).localeCompare(String(b.client), 'ru'));
  if (ui.sort === 'school') {
    rows = rows.slice().sort((a, b) => `${a.school}${a.class_name}`.localeCompare(`${b.school}${b.class_name}`, 'ru'));
  }
  return rows;
}

export function renderTaskHeader() {
  const campaign = S.campaign || {};
  const stats = campaignProgress(campaign);
  $('taskTitle').textContent = campaign.name ? `${campaign.name}` : 'Задания рассылки';
  const badge = $('taskStatusBadge');
  badge.className = 'badge ' + (campaign.status === 'COMPLETED' ? 'ok' : campaign.status === 'STOPPED' ? 'err' : 'mute');
  badge.textContent = statusName(campaign.status);
  const countLabel = (list) => (list && list.length
    ? `${list.length} ${plural(list.length, 'сообщение', 'сообщения', 'сообщений')}`
    : 'нет');
  $('taskMessagesInfo').textContent =
    `КР: ${countLabel(campaign.messages_kr)} · РК: ${countLabel(campaign.messages_rk)}` +
    (campaign.description ? ` · ${campaign.description}` : '');
  renderBulkMessageSelect();
  $('taskUpdatedAt').textContent = S.tasksUi.updatedAt ? fmtTime(S.tasksUi.updatedAt) : '—';
  $('taskExportLink').href = `/api/reports/${S.tasksUi.campaignId}/export`;
  $('taskStopGroup').classList.toggle('hidden', !['RUNNING', 'WAITING_REVIEW'].includes(campaign.status));

  // Две части полосы: подтверждённые задания и задания с готовым черновиком, но без результата.
  const drafted = S.tasks.filter((task) => !DONE_STATUSES.includes(task.status)
    && (task.messages || []).length > 0 && task.messages.every((message) => message.prepared_at)).length;
  const donePercent = stats.total ? (stats.done / stats.total) * 100 : 0;
  const draftPercent = stats.total ? (drafted / stats.total) * 100 : 0;
  const progress = $('taskProgress');
  progress.querySelector('.done').style.width = `${donePercent}%`;
  progress.querySelector('.prep').style.width = `${draftPercent}%`;
  progress.setAttribute('aria-valuenow', String(Math.round(donePercent)));
  $('taskProgressText').textContent = `${stats.done} из ${stats.total} подтверждено` +
    (drafted ? ` · черновики готовы: ${drafted}` : '');

  const counts = campaign.status_counts || {};
  const total = campaign.task_count || 0;
  const chips = [['', 'Все', total], [TODO_FILTER, 'Нужно обработать', total - stats.done]]
    .concat(TASK_STATUSES
      .filter((code) => counts[code])
      .map((code) => [code, statusName(code), counts[code]]));
  $('taskChips').innerHTML = chips.map(([code, label, count]) => `
    <button type="button" class="chip" data-task-status="${code}" aria-pressed="${S.tasksUi.statusFilter === code}">
      ${esc(label)} <small>${count}</small>
    </button>`).join('');
  qa('[data-task-status]', $('taskChips')).forEach((button) => {
    button.addEventListener('click', () => {
      S.tasksUi.statusFilter = button.dataset.taskStatus;
      S.tasksUi.page = 1;
      renderTasks();
    });
  });
}

export function draftBadge(task) {
  const messages = task.messages || [];
  const ready = messages.filter((message) => message.prepared_at).length;
  if (!ready) return '';
  if (messages.length < 2) return '<span class="badge ok">черновик готов</span><br>';
  return `<span class="badge ${ready === messages.length ? 'ok' : 'warn'}">черновики: ${ready} из ${messages.length}</span><br>`;
}

export const maxMessageCount = () => Math.max(1, ...S.tasks.map((task) => (task.messages || []).length));

export function renderBulkMessageSelect() {
  const select = $('taskBulkMessage');
  const total = maxMessageCount();
  const previous = Number(select.value) || 1;
  select.innerHTML = Array.from({ length: total }, (_, index) => `<option value="${index + 1}">№${index + 1}</option>`).join('');
  select.value = String(Math.min(previous, total));
  $('taskBulkMessageWrap').hidden = total < 2;
}

export const prepareLabel = (total, message) =>
  `Подготовить в MAX${total > 1 ? ` ${message.index}` : ''}${message.prepared_at ? ' ✓' : ''}`;

export function prepareButtons(task, className, only) {
  const total = (task.messages || []).length;
  return (only || task.messages || []).map((message) => `
    <button type="button" class="btn small ${className}" data-action="task-prepare" data-id="${task.id}" data-msg="${message.index}"
      title="${message.prepared_at ? 'Черновик уже подготовлен; повторная подготовка заменит текст в поле ввода' : 'Вставить текст сообщения в поле ввода MAX'}">${prepareLabel(total, message)}</button>`).join('');
}

export const statusTone = (status) =>
  (status === 'SENT' ? 'ok' : BAD_STATUSES.includes(status) ? 'err' : 'warn');

// Итог одним нажатием: «Отправлено» / «Не отправлено» (и «Неизвестно» только в карточке).
export function resultButtons(task, withUnknown = false) {
  return `
    <button type="button" class="btn small ok-btn" data-action="task-confirm" data-id="${task.id}" data-result="sent"
      title="Сообщение отправлено вручную в MAX">✓ Отправлено</button>
    <button type="button" class="btn small danger" data-action="task-confirm" data-id="${task.id}" data-result="failed"
      title="Сообщение не удалось отправить">✕ Не отправлено</button>
    ${withUnknown ? `<button type="button" class="btn small ghost" data-action="task-confirm" data-id="${task.id}" data-result="unknown">Неизвестно</button>` : ''}`;
}

export function paintTaskRows() {
  const ui = S.tasksUi;
  const rows = taskFiltered();
  const pageSize = ui.pageSize;
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (ui.page > pages) ui.page = pages;
  const start = (ui.page - 1) * pageSize;
  const visible = rows.slice(start, start + pageSize);

  $('taskListInfo').textContent = `Показано ${visible.length} из ${rows.length}`;
  $('taskRows').innerHTML = visible.length
    ? visible.map((task) => `
      <tr data-task-row="${task.id}" class="${ui.selectedId === task.id ? 'selected' : ''}">
        <td data-label="Получатель">
          <b>${esc(task.client)}</b>
          <span class="muted">${esc(task.phone || 'телефон не указан')}</span>
        </td>
        <td data-label="Школа">${esc(task.school || '—')}</td>
        <td data-label="Класс">${esc(task.class_name || '—')}</td>
        <td data-label="Роль"><span class="badge ${task.recipient_role === 'KR' ? 'ok' : 'mute'}">${task.recipient_role === 'KR' ? 'КР' : 'РК'}</span></td>
        <td data-label="MAX">
          ${draftBadge(task)}
          ${task.status === 'CONTACT_NOT_FOUND' ? `<span class="badge err">${esc(statusName(task.status))}</span><br>` : ''}
          ${task.opened_at ? '<span class="badge mute">чат открыт</span>' : ''}
          ${task.browser_error ? `<span class="badge err" title="${esc(task.browser_error)}">ошибка MAX</span>` : ''}
        </td>
        <td data-label="Статус">
          <span class="badge ${statusTone(task.status)}">${esc(statusName(task.status))}</span>
          ${task.attempts ? `<span class="muted">попыток: ${task.attempts}</span>` : ''}
        </td>
        <td data-label="Результат">
          ${task.operator_confirmed_at
            ? `<span class="badge ${task.operator_result === 'sent' ? 'ok' : task.operator_result === 'failed' ? 'err' : 'mute'}">${esc(statusName(task.status))}</span>`
            : '<span class="muted">не подтверждено</span>'}
        </td>
        <td data-label="Действия">
          <div class="task-actions">
            ${prepareButtons(task, 'primary')}
            <button type="button" class="btn small ghost" data-action="task-rename" data-id="${task.id}" title="Имя по шаблону, фамилия очищается">Переименовать в MAX</button>
            ${DONE_STATUSES.includes(task.status) ? '' : resultButtons(task)}
          </div>
        </td>
      </tr>`).join('')
    : '<tr><td colspan="8" class="empty">Заданий по текущему фильтру нет.</td></tr>';

  qa('[data-task-row]', $('taskRows')).forEach((row) => {
    row.addEventListener('click', (event) => {
      if (event.target.closest('select, button, a')) return;
      selectTask(Number(row.dataset.taskRow));
    });
  });

  $('taskPageInfo').textContent = rows.length
    ? `Показано ${start + 1}–${Math.min(start + pageSize, rows.length)} из ${rows.length}`
    : '';
  $('taskPrev').disabled = ui.page <= 1;
  $('taskNext').disabled = ui.page >= pages;
}

export function renderTasks() {
  renderTaskHeader();
  paintTaskRows();
  renderTaskDetail();
}

export function currentTask() {
  return S.tasks.find((task) => task.id === S.tasksUi.selectedId) || null;
}

export function messageBlocksHtml(task) {
  const messages = task.messages || [];
  if (!messages.length) {
    return `<h3>Текст сообщения</h3>
      <pre class="message">Текст не сформирован: в рассылке нет шаблона для этой роли.</pre>`;
  }
  const editable = EDITABLE_TASK_STATUSES.includes(task.status);
  const hint = messages.length > 1
    ? `<p class="muted m-0 mb-10">Каждая подготовка заменяет текст в поле ввода чата MAX. Сначала отправьте предыдущее сообщение вручную, затем готовьте следующее.</p>`
    : '';
  return hint + messages.map((message) => `
    <div class="msg-block">
      <div class="card-head">
        <h3>${messages.length > 1 ? `Сообщение ${message.index} из ${messages.length}` : 'Текст сообщения'}</h3>
        ${message.prepared_at ? '<span class="badge ok">черновик готов</span>' : ''}
      </div>
      <div class="task-actions mb-8">
        ${prepareButtons(task, 'primary', [message])}
        <button type="button" class="btn small ghost" data-action="task-copy" data-id="${task.id}" data-msg="${message.index}">Копировать текст</button>
        ${editable ? `<button type="button" class="btn small ghost" data-action="task-edit-message" data-id="${task.id}" data-msg="${message.index}">Изменить текст</button>` : ''}
      </div>
      <pre class="message">${esc(message.text)}</pre>
    </div>`).join('');
}

export function renderTaskDetail() {
  const task = currentTask();
  const box = $('taskDetail');
  if (!task) {
    box.innerHTML = `
      <h3>Карточка задания</h3>
      <p class="muted">Выберите получателя в таблице, чтобы увидеть готовый текст, идентификаторы MAX и историю действий.</p>`;
    $('taskSelectedInfo').hidden = true;
    return;
  }
  $('taskSelectedInfo').hidden = false;
  $('taskSelectedInfo').textContent = `${task.client} · ${statusName(task.status)}`;
  box.innerHTML = `
    <div class="card-head">
      <h3>${esc(task.client)}</h3>
      <span class="badge ${task.recipient_role === 'KR' ? 'ok' : 'mute'}">${task.recipient_role === 'KR' ? 'КР' : 'РК'}</span>
      <span class="spacer"></span>
      <span class="badge ${task.status === 'SENT' ? 'ok' : BAD_STATUSES.includes(task.status) ? 'err' : 'warn'}">${esc(statusName(task.status))}</span>
    </div>
    <div class="row mb-10">
      <button type="button" class="btn small ghost" data-action="task-open" data-id="${task.id}">Открыть чат</button>
      <button type="button" class="btn small ghost" data-action="task-rename" data-id="${task.id}" title="Имя по шаблону, фамилия очищается">Переименовать в MAX</button>
    </div>
    ${messageBlocksHtml(task)}
    <h3 class="mt-14">Данные получателя</h3>
    <dl class="kv">
      <dt>Школа</dt><dd>${esc(task.school || '—')}</dd>
      <dt>Класс</dt><dd>${esc(task.class_name || '—')}</dd>
      <dt>Телефон</dt><dd>${esc(task.phone || 'не указан')}</dd>
      <dt>MAX user id</dt><dd>${esc(task.max_user_id || '—')}</dd>
      <dt>Имя пользователя</dt><dd>${esc(task.username || '—')}</dd>
      <dt>Ссылка на чат</dt><dd>${task.chat_link ? `<a href="${esc(task.chat_link)}" target="_blank" rel="noopener">открыть</a>` : '—'}</dd>
      <dt>Попыток</dt><dd>${task.attempts || 0}</dd>
    </dl>
    <h3 class="mt-14">История</h3>
    <dl class="kv">
      <dt>Создано</dt><dd>${esc(fmtDateTime(task.created_at))}</dd>
      <dt>Чат открыт</dt><dd>${esc(fmtDateTime(task.opened_at))}</dd>
      <dt>Черновик готов</dt><dd>${esc(fmtDateTime(task.browser_prepared_at))}</dd>
      <dt>Подтверждено</dt><dd>${esc(fmtDateTime(task.operator_confirmed_at))}</dd>
      <dt>Результат</dt><dd>${esc(task.operator_result || '—')}</dd>
    </dl>
    ${task.error ? `<div class="notice warn mt-10">${esc(task.error)}</div>` : ''}
    ${task.browser_error ? `<div class="notice error mt-10">${esc(task.browser_error)}</div>` : ''}
    <h3 class="mt-14">Результат</h3>
    <div class="field mt-8">
      <span>Примечание к результату (необязательно)</span>
      <textarea id="detail-note" maxlength="500" placeholder="Например: отправлено вручную, ответа нет">${esc(task.error || '')}</textarea>
    </div>
    <div class="task-actions mt-10">${resultButtons(task, true)}</div>
    <label class="inline-field mt-10">Изменить статус вручную
      <select class="inline-select" data-task-status-select="${task.id}" aria-label="Статус задания">
        ${TASK_STATUSES.map((code) => `<option value="${code}" ${code === task.status ? 'selected' : ''}>${esc(statusName(code))}</option>`).join('')}
      </select>
    </label>`;
}

export function bindDetailEvents() {
  $('taskDetail').addEventListener('change', (event) => {
    const select = event.target.closest('[data-task-status-select]');
    if (!select) return;
    updateTaskStatus(Number(select.dataset.taskStatusSelect), select.value)
      .catch((error) => toast(error.message, 'error'));
  });
}

export function selectTask(id) {
  S.tasksUi.selectedId = id;
  paintTaskRows();
  renderTaskDetail();
  // На узком экране карточка лежит под таблицей: подводим к ней, чтобы не искать вручную.
  if (window.matchMedia('(max-width: 1060px)').matches) {
    $('taskDetail').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

export async function updateTaskStatus(taskId, status) {
  await api(`/tasks/${taskId}/status`, { method: 'PATCH', body: JSON.stringify({ status }) });
  toast('Статус задания обновлён');
  await refreshTasks();
}

// Одновременно в MAX выполняется одна операция (то же ограничение есть на сервере).
export async function withMaxLock(action) {
  if (S.maxBusy) {
    toast('В MAX уже выполняется операция. Дождитесь её завершения.', 'warn');
    return;
  }
  S.maxBusy = true;
  try {
    await action();
  } finally {
    S.maxBusy = false;
  }
}

export async function prepareTask(taskId, messageNo = 1) {
  await withMaxLock(async () => {
    const buttons = qa('[data-action="task-prepare"]')
      .filter((node) => Number(node.dataset.id) === taskId && Number(node.dataset.msg || 1) === messageNo);
    buttons.forEach((node) => {
      node.setAttribute('aria-busy', 'true');
      node.disabled = true;
    });
    try {
      const result = await api(`/tasks/${taskId}/prepare-max?message_no=${messageNo}`, { method: 'POST' });
      const task = S.tasks.find((item) => item.id === taskId);
      const multi = task && (task.messages || []).length > 1;
      toast(multi
        ? `Сообщение ${messageNo} подготовлено для ${result.client}. Оно заменило текст в поле ввода; отправка не выполнялась.`
        : `Текст подготовлен для ${result.client}. Отправка не выполнялась.`);
      $('taskLastError').textContent = 'последняя подготовка: успех';
    } catch (error) {
      $('taskLastError').textContent = error.message;
      toast(error.message, 'error');
    } finally {
      buttons.forEach((node) => {
        node.removeAttribute('aria-busy');
        node.disabled = false;
      });
      await refreshTasks();
    }
  });
}

export async function openTaskChat(taskId) {
  await withMaxLock(async () => {
    try {
      const result = await api(`/tasks/${taskId}/open-max`, { method: 'POST' });
      toast(`Чат открыт для ${result.client}. Текст не вставлялся.`);
      // Поиск выполняется во вкладке MAX в подключённом браузере; новую вкладку не открываем.
      $('taskLastError').textContent = 'последнее открытие чата: успех';
    } catch (error) {
      $('taskLastError').textContent = error.message;
      toast(error.message, 'error');
    } finally {
      await refreshTasks();
    }
  });
}

export async function renameTaskContact(taskId) {
  await withMaxLock(async () => {
    const button = qa('[data-action="task-rename"]').find((node) => Number(node.dataset.id) === taskId);
    if (button) {
      button.setAttribute('aria-busy', 'true');
      button.disabled = true;
    }
    try {
      const result = await api(`/tasks/${taskId}/rename-max`, { method: 'POST' });
      if (result.status === 'ALREADY_CORRECT') {
        toast('Имя контакта в MAX уже корректно, изменений не потребовалось. Страница обновлена.');
      } else {
        toast('Контакт переименован в MAX по шаблону. Фамилия очищена.');
      }
      $('taskLastError').textContent = 'последнее переименование: успех';
    } catch (error) {
      $('taskLastError').textContent = error.message;
      toast(error.message, 'error');
    } finally {
      if (button) {
        button.removeAttribute('aria-busy');
        button.disabled = false;
      }
      await refreshTasks();
    }
  });
}

export async function confirmTaskResult(taskId, result) {
  // Примечание берём только из карточки этого же задания.
  const noteField = S.tasksUi.selectedId === taskId ? $('detail-note') : null;
  const note = noteField ? (noteField.value || '').trim() : '';
  await api(`/tasks/${taskId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ result, note: note || null }),
  });
  toast('Результат сохранён');
  await refreshTasks();
}

export async function prepareAll() {
  if (S.bulk.running) {
    toast('Массовая подготовка уже выполняется', 'warn');
    return;
  }
  if (S.maxBusy) {
    toast('В MAX уже выполняется операция. Дождитесь её завершения.', 'warn');
    return;
  }
  const messageNo = Number($('taskBulkMessage').value) || 1;
  const tasks = S.tasks.filter((task) =>
    !DONE_STATUSES.includes(task.status) && (task.messages || []).length >= messageNo);
  if (!tasks.length) {
    toast(`Нет заданий, требующих подготовки сообщения ${messageNo}`, 'warn');
    return;
  }
  const multi = maxMessageCount() > 1;
  const confirmed = await confirmAction(
    'Массовая подготовка черновиков',
    `Будут последовательно обработаны ${tasks.length} ${plural(tasks.length, 'получатель', 'получателя', 'получателей')}` +
    `${multi ? ` (сообщение №${messageNo})` : ''}. ` +
    'Приложение откроет чаты в MAX и вставит текст — отправка НЕ выполняется. ' +
    `${multi ? 'Текст заменит содержимое поля ввода в каждом чате, поэтому предыдущие сообщения нужно отправить заранее. ' : ''}` +
    'Можно остановить процесс в любой момент.',
    { confirmText: 'Начать подготовку', danger: false },
  );
  if (!confirmed) return;
  S.bulk.running = true;
  S.bulk.cancel = false;
  S.maxBusy = true;
  stopAutoRefresh();
  const progressButton = $('taskBulkPrepare');
  progressButton.setAttribute('aria-busy', 'true');
  progressButton.disabled = true;
  const errors = [];
  let prepared = 0;
  let cancelled = false;
  try {
    for (let index = 0; index < tasks.length; index += 1) {
      if (S.bulk.cancel) {
        cancelled = true;
        break;
      }
      const task = tasks[index];
      $('taskLastError').textContent = `Подготовка ${index + 1} из ${tasks.length}: ${task.client}`;
      try {
        await api(`/tasks/${task.id}/prepare-max?message_no=${messageNo}`, { method: 'POST' });
        prepared += 1;
      } catch (error) {
        errors.push(`${task.client}: ${error.message}`);
      }
    }
  } finally {
    S.bulk.running = false;
    S.maxBusy = false;
    progressButton.removeAttribute('aria-busy');
    progressButton.disabled = false;
    await refreshTasks();
    startAutoRefresh();
  }
  const summary = cancelled
    ? `Подготовка остановлена: готово ${prepared} из ${tasks.length}.`
    : `Готово: черновики созданы для ${prepared} из ${tasks.length}. Отправка не выполнялась.`;
  toast(summary, errors.length ? 'warn' : 'ok', errors);
  $('taskLastError').textContent = errors.length ? `Ошибок: ${errors.length}` : 'ошибок нет';
}

export async function openAllChats() {
  const tasks = S.tasks.filter((task) => !DONE_STATUSES.includes(task.status));
  if (!tasks.length) {
    toast('Нет заданий для открытия чатов', 'warn');
    return;
  }
  const confirmed = await confirmAction(
    'Открыть чаты по списку',
    `Приложение откроет ${tasks.length} ${plural(tasks.length, 'чат', 'чата', 'чатов')} в MAX и отметит факт открытия. ` +
    'Тексты сообщений не вставляются. Продолжить?',
    { confirmText: 'Открыть чаты', danger: false },
  );
  if (!confirmed) return;
  if (S.maxBusy) {
    toast('В MAX уже выполняется операция. Дождитесь её завершения.', 'warn');
    return;
  }
  S.bulk.running = true;
  S.maxBusy = true;
  stopAutoRefresh();
  const errors = [];
  let opened = 0;
  try {
    for (const task of tasks) {
      if (S.bulk.cancel) break;
      $('taskLastError').textContent = `Открытие чата: ${task.client}`;
      try {
        await api(`/tasks/${task.id}/open-max`, { method: 'POST' });
        opened += 1;
      } catch (error) {
        errors.push(`${task.client}: ${error.message}`);
      }
    }
  } finally {
    S.bulk.running = false;
    S.maxBusy = false;
    await refreshTasks();
    startAutoRefresh();
  }
  toast(`Открыто чатов: ${opened} из ${tasks.length}.`, errors.length ? 'warn' : 'ok', errors);
}

// --- Автообновление ---------------------------------------------------------

export function autoRefreshEnabled() {
  return $('autoRefreshToggle').checked && S.prefs.refreshMs > 0;
}

export function stopAutoRefresh() {
  clearInterval(S.refreshTimer);
  S.refreshTimer = null;
}

export function startAutoRefresh() {
  stopAutoRefresh();
  if (!autoRefreshEnabled() || !S.tasksUi.campaignId) return;
  S.refreshTimer = setInterval(() => {
    if (S.route !== 'tasks' || S.bulk.running) return;
    if (document.hidden) return;
    if (document.activeElement && $('taskRows').contains(document.activeElement)) return;
    refreshTasks().catch((error) => {
      $('taskLastError').textContent = error.message;
    });
  }, S.prefs.refreshMs);
}
