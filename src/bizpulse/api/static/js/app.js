// BizPulse GUI helpers — Alpine.js components + fetch wrappers.

const STORAGE_KEY = 'bizpulse.api_key';
const TENANT_KEY  = 'bizpulse.tenant';
const ADMIN_KEY   = 'bizpulse.admin_key';
const IMPERSONATING_KEY = 'bizpulse.impersonating';

function bzpApiKey()    { return localStorage.getItem(STORAGE_KEY) || ''; }
function bzpSetApiKey(k){ localStorage.setItem(STORAGE_KEY, k); }
function bzpClearApiKey(){ localStorage.removeItem(STORAGE_KEY); localStorage.removeItem(TENANT_KEY); localStorage.removeItem(IMPERSONATING_KEY); }
function bzpTenant()     { try { return JSON.parse(localStorage.getItem(TENANT_KEY) || 'null'); } catch { return null; } }
function bzpSetTenant(t) { localStorage.setItem(TENANT_KEY, JSON.stringify(t)); }
function bzpAdminKey()   { return localStorage.getItem(ADMIN_KEY) || ''; }
function bzpSetAdminKey(k){ localStorage.setItem(ADMIN_KEY, k); }
function bzpClearAdminKey(){ localStorage.removeItem(ADMIN_KEY); }
function bzpImpersonating(){ return localStorage.getItem(IMPERSONATING_KEY) === '1'; }

async function bzpFetch(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {}, { 'Content-Type': 'application/json' });
  const key = bzpApiKey();
  if (key) headers['X-API-Key'] = key;
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  const text = await r.text();
  let body;
  try { body = JSON.parse(text); } catch { body = text; }
  if (!r.ok) {
    const detail = (body && body.detail) ? body.detail : `HTTP ${r.status}`;
    throw new Error(detail);
  }
  return body;
}

function bzpToast(msg, ms = 2200) {
  let t = document.createElement('div');
  t.className = 'bzp-toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

function bzpRequireLogin() {
  if (!bzpApiKey()) {
    window.location.href = '/ui/';
    return false;
  }
  return true;
}

function bzpFmtCurrency(usd) {
  if (typeof usd !== 'number') return '—';
  if (usd < 0.001) return '$' + usd.toFixed(5);
  if (usd < 1)     return '$' + usd.toFixed(3);
  return '$' + usd.toFixed(2);
}

function bzpFmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function bzpStatusPill(status) {
  const map = {
    pending:        ['neutral', 'pending'],
    ingesting:      ['accent',  'ingesting'],
    embedding:      ['accent',  'embedding'],
    analyzing:      ['accent',  'analyzing'],
    synthesizing:   ['accent',  'synthesizing'],
    critic_review:  ['accent',  'critic'],
    complete:       ['success', 'complete'],
    failed:         ['danger',  'failed'],
  };
  const [tone, label] = map[status] || ['neutral', status];
  return '<span class="bzp-pill bzp-pill-' + tone + '">' + label + '</span>';
}

// --- Alpine components ----------------------------------------------------

document.addEventListener('alpine:init', () => {

  Alpine.data('loginPage', () => ({
    mode: 'login', apiKey: '', name: '', signupCode: '', signupRequiresCode: false, isTest: false, busy: false, error: '',
    async init() {
      if (bzpApiKey()) {
        try { const me = await bzpFetch('/v1/tenants/me'); bzpSetTenant(me); window.location.href = '/ui/dashboard.html'; return; }
        catch (e) { bzpClearApiKey(); }
      }
      try { const policy = await fetch('/v1/tenants/signup-policy').then(r => r.json()); this.signupRequiresCode = !!policy.requires_code; } catch (e) {}
    },
    async submitLogin() {
      this.error = ''; this.busy = true;
      try { bzpSetApiKey(this.apiKey.trim()); const me = await bzpFetch('/v1/tenants/me'); bzpSetTenant(me); window.location.href = '/ui/dashboard.html'; }
      catch (e) { bzpClearApiKey(); this.error = e.message; } finally { this.busy = false; }
    },
    async submitCreate() {
      this.error = ''; this.busy = true;
      try {
        const headers = { 'Content-Type': 'application/json' };
        if (this.signupRequiresCode) headers['X-Signup-Code'] = this.signupCode.trim();
        const r = await fetch('/v1/tenants', { method: 'POST', headers, body: JSON.stringify({ name: this.name.trim(), is_test: !!this.isTest }) });
        const tenant = await r.json();
        if (!r.ok || !tenant.api_key) throw new Error(tenant.detail || JSON.stringify(tenant));
        bzpSetApiKey(tenant.api_key); bzpSetTenant(tenant); window.location.href = '/ui/dashboard.html';
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
  }));

  Alpine.data('topNav', () => ({
    tenant: null, impersonating: false,
    init() { this.tenant = bzpTenant(); this.impersonating = bzpImpersonating(); },
    logout() { bzpClearApiKey(); window.location.href = '/ui/'; },
    returnToAdmin() { localStorage.removeItem(STORAGE_KEY); localStorage.removeItem(TENANT_KEY); localStorage.removeItem(IMPERSONATING_KEY); window.location.href = '/ui/admin.html'; },
  }));

  Alpine.data('dashboardPage', () => ({
    tenant: null, businesses: [], runs: [], usage: null, busy: true,
    async init() {
      if (!bzpRequireLogin()) return;
      this.tenant = bzpTenant();
      try {
        const [businesses, usage] = await Promise.all([bzpFetch('/v1/businesses'), bzpFetch('/v1/tenants/me/usage').catch(() => null)]);
        this.businesses = businesses; this.usage = usage;
        const runLists = await Promise.all(this.businesses.map(b => bzpFetch('/v1/businesses/' + b.id + '/runs')));
        this.runs = runLists.flat().sort((a,b)=> b.started_at.localeCompare(a.started_at)).slice(0, 10);
      } catch (e) { bzpToast(e.message); } finally { this.busy = false; }
    },
    statusPill: bzpStatusPill, fmtTime: bzpFmtTime,
    bizName(id) { const b = this.businesses.find(b => b.id === id); return b ? b.url : id.slice(0, 8) + '…'; },
    quotaPercent() { if (!this.usage || !this.usage.daily_limit) return 0; return Math.min(100, Math.round((this.usage.runs_today / this.usage.daily_limit) * 100)); },
    quotaTone() { const pct = this.quotaPercent(); if (pct >= 100) return 'danger'; if (pct >= 80) return 'warning'; return 'success'; },
  }));

  Alpine.data('newReportPage', () => ({
    url: '', industry: '', country: 'IN', state: '', context: '', num_llms: '',
    busy: false, error: '',
    INDUSTRIES: [], COUNTRIES: [], STATES: {},
    async init() {
      bzpRequireLogin();
      try {
        const [ind, loc] = await Promise.all([bzpFetch('/v1/metadata/industries'), bzpFetch('/v1/metadata/locations')]);
        this.INDUSTRIES = ind;
        this.COUNTRIES = loc.countries;
        this.STATES = loc.states;
        if (this.INDUSTRIES.length > 0) this.industry = this.INDUSTRIES[0].slug;
      } catch (e) { bzpToast('Metadata load failed: ' + e.message); }
    },
    async submit() {
      this.error = ''; this.busy = true;
      try {
        const biz = await bzpFetch('/v1/businesses', { method: 'POST', body: JSON.stringify({ url: this.url.trim(), industry: this.industry }) });
        const bodyPayload = {
          country: this.country,
          state: this.state || null,
          additional_context: this.context.trim() || null
        };
        if (this.num_llms) {
          bodyPayload.num_llms = parseInt(this.num_llms, 10);
        }
        const run = await bzpFetch('/v1/businesses/' + biz.id + '/analyze', {
          method: 'POST',
          body: JSON.stringify(bodyPayload)
        });
        bzpToast('Analysis started — opening report');
        setTimeout(() => { window.location.href = '/ui/report.html?run=' + run.id; }, 600);
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
  }));

  Alpine.data('historyPage', () => ({
    businesses: [], runs: [], busy: true,
    async init() {
      if (!bzpRequireLogin()) return;
      try {
        this.businesses = await bzpFetch('/v1/businesses');
        const runLists = await Promise.all(this.businesses.map(b => bzpFetch('/v1/businesses/' + b.id + '/runs')));
        this.runs = runLists.flat().sort((a,b) => b.started_at.localeCompare(a.started_at));
      } catch (e) { bzpToast(e.message); } finally { this.busy = false; }
    },
    statusPill: bzpStatusPill, fmtTime: bzpFmtTime, fmtCurrency: bzpFmtCurrency,
    bizUrl(id) { const b = this.businesses.find(b => b.id === id); return b ? b.url : ''; },
    bizIndustry(id) { const b = this.businesses.find(b => b.id === id); return b ? (b.industry || '—') : '—'; },
  }));

  // ---- admin ---------------------------------------------------------

  async function adminFetch(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {}, { 'Content-Type': 'application/json', 'X-Admin-Key': bzpAdminKey() });
    const totp = localStorage.getItem('bizpulse.admin_totp') || '';
    if (totp) headers['X-Admin-TOTP'] = totp;
    const r = await fetch(path, Object.assign({}, opts, { headers }));
    const text = await r.text();
    let body; try { body = JSON.parse(text); } catch { body = text; }
    if (!r.ok) throw new Error(body && body.detail ? body.detail : 'HTTP ' + r.status);
    return body;
  }

  Alpine.data('adminPage', () => ({
    authed: false, enabled: true, requiresTotp: false, adminKey: '', totp: '', busy: false, error: '',
    tenants: [], industries: [], locations: { countries: [], states: {} }, activeTab: 'tenants', audit: [], auditLoaded: false,
    cleanupPattern: '', cleanupPreview: [], cleanupBusy: false,
    searchQuery: '', selectedTenantIds: [], editingTenant: null, bulkEditingTenants: null, tenantSubTab: 'actual',
    systemStatus: [
      { name: 'api', healthy: true, details: 'BizPulse Core API' },
      { name: 'qdrant', healthy: false, details: 'Vector Database' },
      { name: 'vllm', healthy: false, details: 'LLM Engine' },
      { name: 'tei-embed', healthy: false, details: 'Embeddings Engine' },
      { name: 'tei-rerank', healthy: false, details: 'Reranker Engine' },
    ],
    diskUsage: [],
    gpuUsage: [],
    topGpuUsers: [],
    async init() {
      try { const s = await fetch('/v1/admin/status').then(r => r.json()); this.enabled = !!s.enabled; this.requiresTotp = !!s.requires_totp; } catch { this.enabled = false; }
      if (bzpAdminKey()) { try { await this.load(); this.authed = true; } catch (e) { bzpClearAdminKey(); } }
      this.checkSystemHealth();
      this.checkResources();
      setInterval(() => this.checkSystemHealth(), 30000);
      setInterval(() => this.checkResources(), 30000);
    },
    async checkResources() {
      if (!bzpAdminKey()) return;
      try {
        const [disk, gpuRes] = await Promise.all([adminFetch('/v1/admin/storage'), adminFetch('/v1/admin/gpu')]);
        this.diskUsage = disk;
        this.gpuUsage = gpuRes.gpus || [];
        this.topGpuUsers = gpuRes.top_users || [];
      } catch (e) { console.error('Resource check failed', e); }
    },
    async terminateProcess(pid) {
      if (!confirm(`Are you sure you want to terminate process ${pid}? This may cause data loss for the user.`)) return;
      try {
        await adminFetch(`/v1/admin/processes/${pid}/terminate`, { method: 'POST' });
        bzpToast(`Termination signal sent to ${pid}`);
        this.checkResources();
      } catch (e) { bzpToast(e.message); }
    },
    async checkSystemHealth() {
      // API is always healthy if we can run this script
      this.systemStatus[0].healthy = true;
      this.systemStatus[0].details = 'BizPulse Core API — Operational';

      const key = bzpAdminKey();
      if (!key) return; // Don't check if not authed

      const headers = { 'X-Admin-Key': key };
      const totp = localStorage.getItem('bizpulse.admin_totp');
      if (totp) headers['X-Admin-TOTP'] = totp;

      const check = async (name, url, desc) => {
        const entry = this.systemStatus.find(s => s.name === name);
        if (!entry) return;
        try {
          const r = await fetch(url, { headers, signal: AbortSignal.timeout(3000) });
          entry.healthy = r.ok;
          if (r.ok) {
            entry.details = `${desc} — Healthy`;
          } else {
            entry.details = (r.status === 502) ? `${desc} — Offline` : `${desc} — Error ${r.status}`;
          }
        } catch (e) {
          entry.healthy = false;
          entry.details = `${desc} — Unreachable`;
        }
      };

      // Qdrant health check
      await check('qdrant', '/v1/admin/proxy/qdrant/healthz', 'Vector Database');
      // LLM / vLLM health check (proxying via admin for cross-origin/auth if needed)
      await check('vllm', '/v1/admin/proxy/vllm/health', 'LLM Engine');
      await check('tei-embed', '/v1/admin/proxy/tei-embed/health', 'Embeddings');
      await check('tei-rerank', '/v1/admin/proxy/tei-rerank/health', 'Reranker');
    },
    async loginAdmin() {
      this.error = ''; this.busy = true;
      try {
        bzpSetAdminKey(this.adminKey.trim());
        if (this.requiresTotp) localStorage.setItem('bizpulse.admin_totp', this.totp.trim());
        await this.load(); this.authed = true;
      } catch (e) { bzpClearAdminKey(); this.error = e.message; } finally { this.busy = false; }
    },
    async load() {
      this.busy = true;
      try {
        const [tenants, industries, locations] = await Promise.all([
          adminFetch('/v1/admin/tenants'), adminFetch('/v1/admin/industries'), adminFetch('/v1/admin/metadata/locations')
        ]);
        this.tenants = Array.isArray(tenants) ? tenants : [];
        this.industries = Array.isArray(industries) ? industries : [];
        this.locations = locations || { countries: [], states: {} };
      } finally { this.busy = false; }
    },
    async loadAudit() { try { this.audit = await adminFetch('/v1/admin/audit?limit=200'); this.auditLoaded = true; } catch (e) { bzpToast(e.message); } },
    signOut() { bzpClearAdminKey(); window.location.reload(); },
    fmtDate(iso) { if (!iso) return '—'; return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }); },
    fmtTime: bzpFmtTime,
    async patchLimit(tenant, raw) {
      const body = (String(raw).trim() === '') ? { clear_daily_limit_override: true } : { daily_limit_override: parseInt(raw, 10) };
      try { const updated = await adminFetch('/v1/admin/tenants/' + tenant.id, { method: 'PATCH', body: JSON.stringify(body) }); Object.assign(tenant, updated); bzpToast('Updated'); }
      catch (e) { bzpToast(e.message); }
    },
    async toggleSuspend(tenant) {
      try { const updated = await adminFetch('/v1/admin/tenants/' + tenant.id, { method: 'PATCH', body: JSON.stringify({ suspended: !tenant.suspended }) }); Object.assign(tenant, updated); bzpToast('Toggled'); }
      catch (e) { bzpToast(e.message); }
    },
    filteredTenants() {
      const isTestTab = this.tenantSubTab === 'test';
      const tenantsList = Array.isArray(this.tenants) ? this.tenants : [];
      const tenantsOfTab = tenantsList.filter(t => t && !!t.is_test === isTestTab);
      const q = (this.searchQuery || '').trim().toLowerCase();
      if (!q) return tenantsOfTab;
      return tenantsOfTab.filter(t => 
        t && (
          (t.name || '').toLowerCase().includes(q) || 
          (t.slug || '').toLowerCase().includes(q) || 
          (t.api_key || '').toLowerCase().includes(q)
        )
      );
    },
    isAllSelected() {
      const filtered = this.filteredTenants();
      if (filtered.length === 0) return false;
      const selectedIds = Array.isArray(this.selectedTenantIds) ? this.selectedTenantIds : [];
      return filtered.every(t => t && selectedIds.includes(t.id));
    },
    toggleSelectAll() {
      const filtered = this.filteredTenants();
      const selectedIds = Array.isArray(this.selectedTenantIds) ? this.selectedTenantIds : [];
      if (this.isAllSelected()) {
        const filteredIds = filtered.map(t => t.id);
        this.selectedTenantIds = selectedIds.filter(id => !filteredIds.includes(id));
      } else {
        const currentIds = new Set(selectedIds);
        filtered.forEach(t => { if (t) currentIds.add(t.id); });
        this.selectedTenantIds = Array.from(currentIds);
      }
    },
    async deleteOne(tenant) {
      if (!confirm('Delete tenant?')) return;
      try {
        await adminFetch('/v1/admin/tenants/' + tenant.id, { method: 'DELETE' });
        const tenantsList = Array.isArray(this.tenants) ? this.tenants : [];
        this.tenants = tenantsList.filter(t => t && t.id !== tenant.id);
        const selectedIds = Array.isArray(this.selectedTenantIds) ? this.selectedTenantIds : [];
        this.selectedTenantIds = selectedIds.filter(id => id !== tenant.id);
        bzpToast('Deleted');
      } catch (e) { bzpToast(e.message); }
    },
    async deleteSelected() {
      const selectedIds = Array.isArray(this.selectedTenantIds) ? this.selectedTenantIds : [];
      if (selectedIds.length === 0) return;
      if (!confirm(`Delete ${selectedIds.length} selected tenant(s)?`)) return;
      try {
        await adminFetch('/v1/admin/tenants/bulk-delete', {
          method: 'POST',
          body: JSON.stringify({ tenant_ids: selectedIds })
        });
        const ids = new Set(selectedIds);
        const tenantsList = Array.isArray(this.tenants) ? this.tenants : [];
        this.tenants = tenantsList.filter(t => t && !ids.has(t.id));
        this.selectedTenantIds = [];
        bzpToast('Selected tenants deleted');
      } catch (e) { bzpToast(e.message); }
    },
    async deleteAll() {
      const filtered = this.filteredTenants();
      if (filtered.length === 0) return;
      if (!confirm(`Are you sure you want to delete all ${filtered.length} matching tenant(s)?`)) return;
      try {
        const filteredIds = filtered.map(t => t.id);
        await adminFetch('/v1/admin/tenants/bulk-delete', {
          method: 'POST',
          body: JSON.stringify({ tenant_ids: filteredIds })
        });
        const ids = new Set(filteredIds);
        const tenantsList = Array.isArray(this.tenants) ? this.tenants : [];
        this.tenants = tenantsList.filter(t => t && !ids.has(t.id));
        const selectedIds = Array.isArray(this.selectedTenantIds) ? this.selectedTenantIds : [];
        this.selectedTenantIds = selectedIds.filter(id => !ids.has(id));
        bzpToast('All matching tenants deleted');
      } catch (e) { bzpToast(e.message); }
    },
    editSelected() {
      const selectedIds = Array.isArray(this.selectedTenantIds) ? this.selectedTenantIds : [];
      if (selectedIds.length === 0) return;
      this.openBulkEditModal(selectedIds);
    },
    editAll() {
      const filtered = this.filteredTenants();
      if (filtered.length === 0) return;
      const filteredIds = filtered.map(t => t.id);
      this.openBulkEditModal(filteredIds);
    },
    openBulkEditModal(ids) {
      this.bulkEditingTenants = {
        targetIds: ids,
        updateLimit: false,
        daily_limit_override: '',
        clear_daily_limit_override: false,
        updateSuspended: false,
        suspended: false,
        updateIsTest: false,
        is_test: false,
        updateNotes: false,
        notes: ''
      };
    },
    closeBulkEditModal() {
      this.bulkEditingTenants = null;
    },
    async saveBulkEditModal() {
      if (!this.bulkEditingTenants) return;
      const targetIds = this.bulkEditingTenants.targetIds;
      
      const body = {
        tenant_ids: targetIds
      };
      
      if (this.bulkEditingTenants.updateLimit) {
        body.update_limit = true;
        const overrideVal = String(this.bulkEditingTenants.daily_limit_override || '').trim();
        if (this.bulkEditingTenants.clear_daily_limit_override || overrideVal === '') {
          body.clear_daily_limit_override = true;
          body.daily_limit_override = null;
        } else {
          body.daily_limit_override = parseInt(overrideVal, 10);
          body.clear_daily_limit_override = false;
        }
      }
      
      if (this.bulkEditingTenants.updateSuspended) {
        body.update_suspended = true;
        body.suspended = this.bulkEditingTenants.suspended === true || this.bulkEditingTenants.suspended === 'true';
      }
      
      if (this.bulkEditingTenants.updateIsTest) {
        body.update_is_test = true;
        body.is_test = this.bulkEditingTenants.is_test === true || this.bulkEditingTenants.is_test === 'true';
      }
      
      if (this.bulkEditingTenants.updateNotes) {
        body.update_notes = true;
        body.notes = (this.bulkEditingTenants.notes || '').trim() || null;
      }
      
      try {
        const updatedList = await adminFetch('/v1/admin/tenants/bulk-patch', {
          method: 'PATCH',
          body: JSON.stringify(body)
        });
        
        const tenantsList = Array.isArray(this.tenants) ? this.tenants : [];
        const updatedMap = new Map(updatedList.map(t => [t.id, t]));
        
        this.tenants = tenantsList.map(t => {
          if (t && updatedMap.has(t.id)) {
            return updatedMap.get(t.id);
          }
          return t;
        });
        
        this.closeBulkEditModal();
        this.selectedTenantIds = [];
        bzpToast(`Updated ${updatedList.length} tenant(s)`);
      } catch (e) {
        bzpToast(e.message);
      }
    },
    openEditModal(tenant) {
      this.editingTenant = {
        id: tenant.id,
        name: tenant.name,
        daily_limit_override: tenant.daily_limit_override !== null ? tenant.daily_limit_override : '',
        notes: tenant.notes || '',
        suspended: !!tenant.suspended,
        is_test: !!tenant.is_test
      };
    },
    closeEditModal() {
      this.editingTenant = null;
    },
    async saveEditModal() {
      if (!this.editingTenant) return;
      const id = this.editingTenant.id;
      const overrideVal = String(this.editingTenant.daily_limit_override || '').trim();
      const body = {
        name: (this.editingTenant.name || '').trim(),
        suspended: !!this.editingTenant.suspended,
        notes: (this.editingTenant.notes || '').trim() || null,
        is_test: !!this.editingTenant.is_test
      };
      if (overrideVal === '') {
        body.clear_daily_limit_override = true;
        body.daily_limit_override = null;
      } else {
        body.daily_limit_override = parseInt(overrideVal, 10);
        body.clear_daily_limit_override = false;
      }
      try {
        const updated = await adminFetch('/v1/admin/tenants/' + id, {
          method: 'PATCH',
          body: JSON.stringify(body)
        });
        const tenantsList = Array.isArray(this.tenants) ? this.tenants : [];
        const idx = tenantsList.findIndex(t => t && t.id === id);
        if (idx !== -1) {
          this.tenants[idx] = updated;
        }
        this.closeEditModal();
        bzpToast('Tenant updated');
      } catch (e) { bzpToast(e.message); }
    },
    async copyKey(t) { try { await navigator.clipboard.writeText(t.api_key); bzpToast('Copied'); } catch (e) {} },
    async impersonate(t) {
      if (!confirm('Sign in as ' + t.name + '?')) return;
      try {
        const r = await adminFetch('/v1/admin/tenants/' + t.id + '/impersonate', { method: 'POST' });
        bzpSetApiKey(r.api_key); bzpSetTenant({ id: r.tenant_id, name: r.name, slug: r.slug, api_key: r.api_key });
        localStorage.setItem(IMPERSONATING_KEY, '1'); window.location.href = '/ui/dashboard.html';
      } catch (e) { bzpToast(e.message); }
    },
    async addIndustry() {
      const slug = prompt('Slug:'); if (!slug) return;
      const name = prompt('Name:'); if (!name) return;
      const desc = prompt('Description:');
      try {
        const body = { slug, name, description: desc || '', ontology: { entities: ['Business'], regulations: [], metrics: [] } };
        await adminFetch('/v1/admin/industries', { method: 'POST', body: JSON.stringify(body) });
        bzpToast('Added'); await this.load();
      } catch (e) { bzpToast(e.message); }
    },
    async deleteIndustry(p) {
      if (!confirm('Delete ' + p.name + '?')) return;
      try { await adminFetch('/v1/admin/industries/' + p.slug, { method: 'DELETE' }); bzpToast('Deleted'); await this.load(); }
      catch (e) { bzpToast(e.message); }
    },
    async addCountry() {
      const code = prompt('Country code (e.g. US, IN):'); if (!code) return;
      const name = prompt('Country name:'); if (!name) return;
      this.locations.countries = [...this.locations.countries, { code: code.toUpperCase(), name }];
      await this.saveLocations();
    },
    async addState() {
      const country = prompt('Country code for this state (e.g. IN):'); if (!country) return;
      const code = prompt('State slug (e.g. maharashtra):'); if (!code) return;
      const name = prompt('State display name:'); if (!name) return;
      const states = this.locations.states[country] || [];
      this.locations.states[country] = [...states, { code, name }];
      await this.saveLocations();
    },
    async saveLocations() {
      try { await adminFetch('/v1/admin/metadata/locations', { method: 'POST', body: JSON.stringify(this.locations) }); bzpToast('Locations updated'); }
      catch (e) { bzpToast(e.message); }
    },
    async dryRunCleanup() {
      this.cleanupBusy = true;
      try { const r = await adminFetch('/v1/admin/tenants/cleanup', { method: 'POST', body: JSON.stringify({ pattern: this.cleanupPattern, dry_run: true }) }); this.cleanupPreview = r.matched || []; }
      finally { this.cleanupBusy = false; }
    },
    async confirmAndCleanup() {
      if (prompt('Type DELETE:') !== 'DELETE') return;
      this.cleanupBusy = true;
      try { await adminFetch('/v1/admin/tenants/cleanup', { method: 'POST', body: JSON.stringify({ pattern: this.cleanupPattern, dry_run: false, confirm_token: 'DELETE' }) }); await this.load(); this.cleanupPreview = []; this.cleanupPattern = ''; }
      finally { this.cleanupBusy = false; }
    }
  }));

  Alpine.data('reportPage', () => ({
    runId: '', run: null, business: null, busy: true, error: '', activeTab: 'strategy', retrying: false,
    agentTraces() {
      const fromRun = this.run?.agent_traces || [];
      const fromStrategy = this.run?.final_output?.agent_traces || [];
      const seen = new Set(); const out = [];
      for (const t of [...fromRun, ...fromStrategy]) {
        const k = (t.id || '') + ':' + (t.agent || '');
        if (seen.has(k)) continue; seen.add(k); out.push(t);
      }
      return out;
    },
    async init() {
      if (!bzpRequireLogin()) return;
      const params = new URLSearchParams(window.location.search); this.runId = params.get('run') || '';
      if (!this.runId) { this.error = 'Missing run id'; this.busy = false; return; }
      try {
        this.run = await bzpFetch('/v1/runs/' + this.runId);
        if (this.run.business_id) this.business = await bzpFetch('/v1/businesses/' + this.run.business_id);
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
    async retry() {
      if (!this.run?.business_id) return; this.retrying = true;
      try {
        const newRun = await bzpFetch('/v1/businesses/' + this.run.business_id + '/analyze', {
          method: 'POST',
          body: JSON.stringify({ country: 'IN', state: null })
        });
        window.location.href = '/ui/report.html?run=' + newRun.id;
      } catch (e) { bzpToast(e.message); this.retrying = false; }
    },
    async downloadReport() {
      try {
        const key = bzpApiKey();
        const url = `/v1/runs/${this.runId}/download`;
        const r = await fetch(url, { headers: { 'X-API-Key': key } });
        if (!r.ok) throw new Error('Download failed');
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `BizPulse_Report_${this.runId.slice(0,8)}.md`;
        a.click();
      } catch (e) { bzpToast(e.message); }
    },
    async downloadPdf() {
      try {
        const key = bzpApiKey();
        const url = `/v1/runs/${this.runId}/pdf`;
        const r = await fetch(url, { headers: { 'X-API-Key': key } });
        if (!r.ok) throw new Error('PDF generation failed');
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `BizPulse_Report_${this.runId.slice(0,8)}.pdf`;
        a.click();
      } catch (e) { bzpToast(e.message); }
    },
    statusPill: bzpStatusPill, fmtTime: bzpFmtTime, fmtCurrency: bzpFmtCurrency,
  }));

});
