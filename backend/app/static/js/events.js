/* Делегирование действий и привязка обработчиков событий. */
import { createCampaign, deleteCampaign, deleteSelectedCampaigns, filteredCampaigns, loadCampaigns, openCampaignMessagesDialog, openTaskMessageDialog, pickerContacts, previewCampaign, renderCampaigns, renderPicker, startCampaign, stopCampaign } from './campaigns.js';
import { copyToClipboard, deleteContactById, deleteSelectedContacts, exportContacts, filteredContacts, loadContacts, openContactDialog, renderContacts } from './contacts.js';
import { $, api, debounce, qa, S, savePrefs } from './core.js';
import { applyPrefs, applyTheme } from './dashboard.js';
import { previewImport, readImportFile, renderImport, resetImport, runImport } from './import.js';
import { checkHealth, go, toggleSidebar } from './router.js';
import { addClassToSchool, classOptions, createSchoolAndClass, deleteClass, deleteSchool, loadSchools, renameClass, renameSchool, renderSchoolOptions, renderSchools, setAllCollapsed, toggleCollapse } from './schools.js';
import { confirmTaskResult, openAllChats, openTaskChat, paintTaskRows, prepareAll, prepareTask, refreshTasks, renameTaskContact, startAutoRefresh, stopAutoRefresh } from './tasks.js';
import { toast } from './ui.js';

// --- Делегирование действий -------------------------------------------------

export const ACTIONS = {
  'school-create': () => createSchoolAndClass(),
  'school-add-class': (id) => addClassToSchool(id),
  'school-rename': (id) => renameSchool(id),
  'school-delete': (id) => deleteSchool(id),
  'class-rename': (id) => renameClass(id),
  'class-delete': (id) => deleteClass(id),
  'collapse-toggle': (id, element) => toggleCollapse(element),
  'collapse-all': (id, element) => setAllCollapsed(element.dataset.scope, true),
  'collapse-none': (id, element) => setAllCollapsed(element.dataset.scope, false),
  'contact-edit': (id) => openContactDialog(id),
  'contact-delete': (id) => deleteContactById(id),
  'contact-create': () => openContactDialog(null),
  'copy': (id, element) => copyToClipboard(element.dataset.copy || ''),
  'campaign-open': (id) => go('tasks', { campaignId: id }),
  'campaign-start': (id) => startCampaign(id),
  'campaign-stop': (id) => stopCampaign(id),
  'campaign-delete': (id) => deleteCampaign(id),
  'campaign-export': (id) => window.open(`/api/reports/${id}/export`, '_blank', 'noopener'),
  'task-prepare': (id, node) => prepareTask(id, Number(node.dataset.msg) || 1),
  'task-open': (id) => openTaskChat(id),
  'task-rename': (id) => renameTaskContact(id),
  'task-copy': (id, node) => {
    const task = S.tasks.find((item) => item.id === id) || {};
    const entry = (task.messages || []).find((item) => item.index === (Number(node.dataset.msg) || 1));
    return copyToClipboard(entry ? entry.text : (task.message || ''));
  },
  'task-confirm': (id) => confirmTaskResult(id),
  'task-edit-message': (id, node) => openTaskMessageDialog(id, Number(node.dataset.msg) || 1),
  'check-health': () => checkHealth(),
  'refresh-campaigns': () => loadCampaigns().then(() => toast('Список рассылок обновлён')),
};

document.addEventListener('click', (event) => {
  const routeTarget = event.target.closest('[data-route]');
  if (routeTarget) {
    go(routeTarget.dataset.route);
    return;
  }
  const actionTarget = event.target.closest('[data-action]');
  if (!actionTarget) return;
  const handler = ACTIONS[actionTarget.dataset.action];
  if (!handler) return;
  event.preventDefault();
  Promise.resolve(handler(Number(actionTarget.dataset.id), actionTarget))
    .catch((error) => toast(error.message, 'error'));
});

// --- Привязка обработчиков ---------------------------------------------------

export function bindEvents() {
  qa('.nav button').forEach((button) => {
    button.addEventListener('click', () => go(button.dataset.route));
  });
  $('menuBtn').addEventListener('click', () => toggleSidebar(true));
  $('scrim').addEventListener('click', () => toggleSidebar(false));
  $('themeBtn').addEventListener('click', () => applyTheme(S.prefs.theme === 'dark' ? 'light' : 'dark'));

  $('schoolSearch').addEventListener('input', debounce(renderSchools, 150));
  $('schoolsRefresh').addEventListener('click', () => loadSchools().then(() => toast('Данные школ обновлены')).catch((error) => toast(error.message, 'error')));
  $('btnAddSchool').addEventListener('click', () => ACTIONS['school-create']());

  $('contactsRefresh').addEventListener('click', () => loadContacts().then(() => toast('Список контактов обновлён')).catch((error) => toast(error.message, 'error')));
  $('btnAddContact').addEventListener('click', () => openContactDialog(null));
  $('contactSearch').addEventListener('input', debounce(() => {
    S.contactsUi.q = $('contactSearch').value.trim();
    S.contactsUi.page = 1;
    loadContacts().catch((error) => toast(error.message, 'error'));
  }, 250));
  $('contactSchool').addEventListener('change', () => {
    S.contactsUi.school = $('contactSchool').value;
    S.contactsUi.klass = '';
    S.contactsUi.page = 1;
    $('contactClass').innerHTML = classOptions(S.contactsUi.school, '');
    loadContacts().catch((error) => toast(error.message, 'error'));
  });
  $('contactClass').addEventListener('change', () => {
    S.contactsUi.klass = $('contactClass').value;
    S.contactsUi.page = 1;
    loadContacts().catch((error) => toast(error.message, 'error'));
  });
  $('contactRole').addEventListener('change', () => {
    S.contactsUi.role = $('contactRole').value;
    S.contactsUi.page = 1;
    renderContacts();
  });
  $('contactOptOut').addEventListener('change', () => {
    S.contactsUi.optedOut = $('contactOptOut').value;
    S.contactsUi.page = 1;
    loadContacts().catch((error) => toast(error.message, 'error'));
  });
  $('contactReset').addEventListener('click', () => {
    Object.assign(S.contactsUi, { q: '', school: '', klass: '', role: '', optedOut: '', page: 1 });
    $('contactSearch').value = '';
    $('contactRole').value = '';
    $('contactOptOut').value = '';
    renderSchoolOptions();
    loadContacts().catch((error) => toast(error.message, 'error'));
  });
  $('contactPageSize').addEventListener('change', () => {
    S.contactsUi.pageSize = Number($('contactPageSize').value);
    S.contactsUi.page = 1;
    renderContacts();
  });
  $('contactPrev').addEventListener('click', () => { S.contactsUi.page -= 1; renderContacts(); });
  $('contactNext').addEventListener('click', () => { S.contactsUi.page += 1; renderContacts(); });
  $('selectAllContacts').addEventListener('change', () => {
    const ui = S.contactsUi;
    const pageIds = filteredContacts()
      .slice((ui.page - 1) * ui.pageSize, ui.page * ui.pageSize)
      .map((item) => item.id);
    if ($('selectAllContacts').checked) pageIds.forEach((id) => ui.selected.add(id));
    else pageIds.forEach((id) => ui.selected.delete(id));
    renderContacts();
  });
  $('btnBulkDeleteContacts').addEventListener('click', () => deleteSelectedContacts().catch((error) => toast(error.message, 'error')));
  $('btnClearContactSelection').addEventListener('click', () => {
    S.contactsUi.selected.clear();
    renderContacts();
  });
  $('btnExportContacts').addEventListener('click', () => exportContacts());

  $('importFile').addEventListener('change', () => readImportFile($('importFile').files[0] || null));
  $('importPreviewBtn').addEventListener('click', () => previewImport().catch((error) => toast(error.message, 'error')));
  $('importRun').addEventListener('click', () => runImport().catch((error) => toast(error.message, 'error')));
  $('importReset').addEventListener('click', resetImport);
  $('importShowAll').addEventListener('click', () => {
    S.importUi.showAll = !S.importUi.showAll;
    renderImport();
  });
  const drop = $('importDrop');
  ['dragenter', 'dragover'].forEach((type) => drop.addEventListener(type, (event) => {
    event.preventDefault();
    drop.classList.add('drag');
  }));
  ['dragleave', 'drop'].forEach((type) => drop.addEventListener(type, (event) => {
    event.preventDefault();
    drop.classList.remove('drag');
  }));
  drop.addEventListener('drop', (event) => {
    const file = event.dataTransfer && event.dataTransfer.files[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    $('importFile').files = transfer.files;
    readImportFile(file);
  });
}

export function bindCampaignEvents() {
  $('recipientSearch').addEventListener('input', debounce(renderPicker, 150));
  $('btnSelectAllRecipients').addEventListener('click', () => {
    pickerContacts().forEach((contact) => {
      if (!contact.opted_out) S.recipients.selected.add(contact.id);
    });
    renderPicker();
    toast(`Выбрано получателей: ${S.recipients.selected.size}`);
  });
  $('btnClearRecipients').addEventListener('click', () => {
    S.recipients.selected.clear();
    renderPicker();
  });
  $('campaignPreviewBtn').addEventListener('click', previewCampaign);
  $('campaignCreateBtn').addEventListener('click', () => createCampaign().catch((error) => toast(error.message, 'error')));
  $('campaignSearch').addEventListener('input', debounce(() => {
    S.campaignsUi.q = $('campaignSearch').value.trim();
    S.campaignsUi.page = 1;
    renderCampaigns();
  }, 200));
  $('campaignStatusFilter').addEventListener('change', () => {
    S.campaignsUi.status = $('campaignStatusFilter').value;
    S.campaignsUi.page = 1;
    renderCampaigns();
  });
  $('campaignsRefresh').addEventListener('click', () => loadCampaigns().then(() => toast('Список рассылок обновлён')).catch((error) => toast(error.message, 'error')));
  $('campaignPrev').addEventListener('click', () => { S.campaignsUi.page -= 1; renderCampaigns(); });
  $('campaignNext').addEventListener('click', () => { S.campaignsUi.page += 1; renderCampaigns(); });
  $('selectAllCampaigns').addEventListener('change', () => {
    const ui = S.campaignsUi;
    const pageIds = filteredCampaigns()
      .slice((ui.page - 1) * ui.pageSize, ui.page * ui.pageSize)
      .map((item) => item.id);
    if ($('selectAllCampaigns').checked) pageIds.forEach((id) => ui.selected.add(id));
    else pageIds.forEach((id) => ui.selected.delete(id));
    renderCampaigns();
  });
  $('btnBulkDeleteCampaigns').addEventListener('click', () => deleteSelectedCampaigns().catch((error) => toast(error.message, 'error')));
  $('btnClearCampaignSelection').addEventListener('click', () => {
    S.campaignsUi.selected.clear();
    renderCampaigns();
  });
}

export function bindTaskEvents() {
  $('taskBack').addEventListener('click', () => go('campaigns'));
  $('taskRefreshBtn').addEventListener('click', () => refreshTasks().then(() => toast('Статусы обновлены')).catch((error) => toast(error.message, 'error')));
  $('taskStopBtn').addEventListener('click', () => stopCampaign(S.tasksUi.campaignId).catch((error) => toast(error.message, 'error')));
  $('taskEditMessagesBtn').addEventListener('click', () => openCampaignMessagesDialog());
  $('taskSearch').addEventListener('input', debounce(() => {
    S.tasksUi.q = $('taskSearch').value.trim();
    S.tasksUi.page = 1;
    paintTaskRows();
  }, 200));
  $('taskRoleFilter').addEventListener('change', () => {
    S.tasksUi.role = $('taskRoleFilter').value;
    S.tasksUi.page = 1;
    paintTaskRows();
  });
  $('taskSort').addEventListener('change', () => {
    S.tasksUi.sort = $('taskSort').value;
    paintTaskRows();
  });
  $('taskPageSize').addEventListener('change', () => {
    S.tasksUi.pageSize = Number($('taskPageSize').value);
    S.tasksUi.page = 1;
    paintTaskRows();
  });
  $('taskPrev').addEventListener('click', () => { S.tasksUi.page -= 1; paintTaskRows(); });
  $('taskNext').addEventListener('click', () => { S.tasksUi.page += 1; paintTaskRows(); });
  $('taskBulkPrepare').addEventListener('click', () => prepareAll().catch((error) => toast(error.message, 'error')));
  $('taskBulkOpen').addEventListener('click', () => openAllChats().catch((error) => toast(error.message, 'error')));
  $('autoRefreshToggle').addEventListener('change', () => {
    if ($('autoRefreshToggle').checked) startAutoRefresh();
    else stopAutoRefresh();
  });
}

export function bindSettingsEvents() {
  $('themeSelect').addEventListener('change', () => applyTheme($('themeSelect').value));
  $('refreshInterval').addEventListener('change', () => {
    S.prefs.refreshMs = Number($('refreshInterval').value);
    savePrefs();
    startAutoRefresh();
    toast(S.prefs.refreshMs ? `Автообновление: каждые ${S.prefs.refreshMs / 1000} с` : 'Автообновление отключено');
  });
  $('pageSizeDefault').addEventListener('change', () => {
    S.prefs.pageSize = Number($('pageSizeDefault').value);
    savePrefs();
    applyPrefs();
    renderContacts();
    toast(`Строк на странице: ${S.prefs.pageSize}`);
  });
  $('settingsCheckHealth').addEventListener('click', () => checkHealth().then(() => toast('Сервер проверен')));
}
