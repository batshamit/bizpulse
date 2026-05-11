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
  if (usd < 0.001) return `$${usd.toFixed(5)}`;
  if (usd < 1)     return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
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
  return `<span class="bzp-pill bzp-pill-${tone}">${label}</span>`;
}

// --- Alpine components ----------------------------------------------------

document.addEventListener('alpine:init', () => {

  Alpine.data('loginPage', () => ({
    mode: 'login',           // 'login' or 'create'
    apiKey: '',
    name: '',
    signupCode: '',
    signupRequiresCode: false,
    busy: false,
    error: '',

    async init() {
      // If already logged in, jump to dashboard.
      if (bzpApiKey()) {
        try {
          const me = await bzpFetch('/v1/tenants/me');
          bzpSetTenant(me);
          window.location.href = '/ui/dashboard.html';
          return;
        } catch (e) { bzpClearApiKey(); }
      }
      // Find out whether the operator has gated signup.
      try {
        const policy = await fetch('/v1/tenants/signup-policy').then(r => r.json());
        this.signupRequiresCode = !!policy.requires_code;
      } catch (e) { /* default false */ }
    },

    async submitLogin() {
      this.error = '';
      this.busy = true;
      try {
        bzpSetApiKey(this.apiKey.trim());
        const me = await bzpFetch('/v1/tenants/me');
        bzpSetTenant(me);
        window.location.href = '/ui/dashboard.html';
      } catch (e) {
        bzpClearApiKey();
        this.error = e.message;
      } finally { this.busy = false; }
    },

    async submitCreate() {
      this.error = '';
      this.busy = true;
      try {
        const headers = { 'Content-Type': 'application/json' };
        if (this.signupRequiresCode) {
          headers['X-Signup-Code'] = this.signupCode.trim();
        }
        const r = await fetch('/v1/tenants', {
          method: 'POST',
          headers,
          body: JSON.stringify({ name: this.name.trim() }),
        });
        const tenant = await r.json();
        if (!r.ok || !tenant.api_key) {
          const detail = tenant.detail || JSON.stringify(tenant);
          throw new Error(detail);
        }
        bzpSetApiKey(tenant.api_key);
        bzpSetTenant(tenant);
        window.location.href = '/ui/dashboard.html';
      } catch (e) {
        this.error = e.message;
      } finally { this.busy = false; }
    },
  }));

  Alpine.data('topNav', () => ({
    tenant: null,
    impersonating: false,
    init() {
      this.tenant = bzpTenant();
      this.impersonating = bzpImpersonating();
    },
    logout() { bzpClearApiKey(); window.location.href = '/ui/'; },
    returnToAdmin() {
      // Clear tenant session but keep admin key so /ui/admin.html auto-resumes.
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(TENANT_KEY);
      localStorage.removeItem(IMPERSONATING_KEY);
      window.location.href = '/ui/admin.html';
    },
  }));

  Alpine.data('dashboardPage', () => ({
    tenant: null,
    businesses: [],
    runs: [],
    usage: null,
    busy: true,
    async init() {
      if (!bzpRequireLogin()) return;
      this.tenant = bzpTenant();
      try {
        const [businesses, usage] = await Promise.all([
          bzpFetch('/v1/businesses'),
          bzpFetch('/v1/tenants/me/usage').catch(() => null),
        ]);
        this.businesses = businesses;
        this.usage = usage;
        const runLists = await Promise.all(
          this.businesses.map(b => bzpFetch(`/v1/businesses/${b.id}/runs`))
        );
        this.runs = runLists.flat().sort((a,b)=> b.started_at.localeCompare(a.started_at)).slice(0, 10);
      } catch (e) { bzpToast(e.message); }
      finally { this.busy = false; }
    },
    statusPill: bzpStatusPill,
    fmtTime: bzpFmtTime,
    bizName(id) {
      const b = this.businesses.find(b => b.id === id);
      return b ? b.url : id.slice(0, 8) + '…';
    },
    quotaPercent() {
      if (!this.usage || !this.usage.daily_limit) return 0;
      return Math.min(100, Math.round((this.usage.runs_today / this.usage.daily_limit) * 100));
    },
    quotaTone() {
      const pct = this.quotaPercent();
      if (pct >= 100) return 'danger';
      if (pct >= 80)  return 'warning';
      return 'success';
    },
  }));

  Alpine.data('newReportPage', () => ({
    url: '', industry: 'fintech', country: 'IN', state: '',
    busy: false, error: '',
    INDUSTRIES: ['fintech', 'real_estate', 'construction_materials'],
    COUNTRIES: [
      { code: 'IN', name: 'India' },
      { code: 'EU', name: 'European Union' },
      { code: 'US', name: 'United States' },
      { code: 'GB', name: 'United Kingdom' },
    ],
    STATES_IN: [
      { code: '', name: '— None / All India —' },
      { code: 'maharashtra',     name: 'Maharashtra' },
      { code: 'karnataka',       name: 'Karnataka' },
      { code: 'tamil_nadu',      name: 'Tamil Nadu' },
      { code: 'delhi',           name: 'Delhi' },
      { code: 'uttar_pradesh',   name: 'Uttar Pradesh' },
    ],
    init() { bzpRequireLogin(); },
    async submit() {
      this.error = '';
      this.busy = true;
      try {
        const biz = await bzpFetch('/v1/businesses', {
          method: 'POST',
          body: JSON.stringify({ url: this.url.trim(), industry: this.industry }),
        });
        const run = await bzpFetch(`/v1/businesses/${biz.id}/analyze`, { method: 'POST' });
        bzpToast('Analysis started — opening report');
        setTimeout(() => {
          window.location.href = `/ui/report.html?run=${run.id}`;
        }, 600);
      } catch (e) { this.error = e.message; }
      finally { this.busy = false; }
    },
  }));

  Alpine.data('historyPage', () => ({
    businesses: [],
    runs: [],
    busy: true,
    async init() {
      if (!bzpRequireLogin()) return;
      try {
        this.businesses = await bzpFetch('/v1/businesses');
        const runLists = await Promise.all(
          this.businesses.map(b => bzpFetch(`/v1/businesses/${b.id}/runs`))
        );
        this.runs = runLists.flat().sort((a,b) => b.started_at.localeCompare(a.started_at));
      } catch (e) { bzpToast(e.message); }
      finally { this.busy = false; }
    },
    statusPill: bzpStatusPill,
    fmtTime: bzpFmtTime,
    bizUrl(id) {
      const b = this.businesses.find(b => b.id === id);
      return b ? b.url : '';
    },
    bizIndustry(id) {
      const b = this.businesses.find(b => b.id === id);
      return b ? (b.industry || '—') : '—';
    },
  }));

  // ---- admin ---------------------------------------------------------

  function bzpAdminTotp() { return localStorage.getItem('bizpulse.admin_totp') || ''; }
  function bzpSetAdminTotp(v) { localStorage.setItem('bizpulse.admin_totp', v); }
  function bzpClearAdminTotp() { localStorage.removeItem('bizpulse.admin_totp'); }

  async function adminFetch(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {}, {
      'Content-Type': 'application/json',
      'X-Admin-Key': bzpAdminKey(),
    });
    const totp = bzpAdminTotp();
    if (totp) headers['X-Admin-TOTP'] = totp;
    const r = await fetch(path, Object.assign({}, opts, { headers }));
    const text = await r.text();
    let body; try { body = JSON.parse(text); } catch { body = text; }
    if (!r.ok) throw new Error(body && body.detail ? body.detail : `HTTP ${r.status}`);
    return body;
  }

  Alpine.data('adminPage', () => ({
    authed: false,
    enabled: true,
    requiresTotp: false,
    adminKey: '',
    totp: '',
    busy: false,
    error: '',
    tenants: [],
    activeTab: 'tenants',
    audit: [],
    auditLoaded: false,
    cleanupPattern: '',
    cleanupPreview: [],
    cleanupBusy: false,

    async init() {
      try {
        const s = await fetch('/v1/admin/status').then(r => r.json());
        this.enabled = !!s.enabled;
        this.requiresTotp = !!s.requires_totp;
      } catch { this.enabled = false; }

      if (bzpAdminKey()) {
        try {
          await this.load();
          this.authed = true;
        } catch (e) { bzpClearAdminKey(); bzpClearAdminTotp(); }
      }
    },

    async loginAdmin() {
      this.error = '';
      this.busy = true;
      try {
        bzpSetAdminKey(this.adminKey.trim());
        if (this.requiresTotp) bzpSetAdminTotp(this.totp.trim());
        else bzpClearAdminTotp();
        await this.load();
        this.authed = true;
      } catch (e) {
        bzpClearAdminKey();
        bzpClearAdminTotp();
        this.error = e.message;
      } finally { this.busy = false; }
    },

    async load() {
      this.busy = true;
      try {
        this.tenants = await adminFetch('/v1/admin/tenants');
      } finally { this.busy = false; }
    },

    async loadAudit() {
      try {
        this.audit = await adminFetch('/v1/admin/audit?limit=200');
        this.auditLoaded = true;
      } catch (e) { bzpToast('Audit load failed: ' + e.message); }
    },

    signOut() {
      bzpClearAdminKey(); bzpClearAdminTotp();
      window.location.reload();
    },

    fmtDate(iso) {
      if (!iso) return '—';
      return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    },
    fmtTime: bzpFmtTime,

    async patchLimit(tenant, raw) {
      const trimmed = String(raw).trim();
      const body = (trimmed === '')
        ? { clear_daily_limit_override: true }
        : { daily_limit_override: parseInt(trimmed, 10) };
      try {
        const updated = await adminFetch(`/v1/admin/tenants/${tenant.id}`, {
          method: 'PATCH', body: JSON.stringify(body),
        });
        Object.assign(tenant, updated);
        bzpToast(`Limit updated for ${tenant.name}`);
      } catch (e) { bzpToast('Update failed: ' + e.message); }
    },

    async toggleSuspend(tenant) {
      try {
        const updated = await adminFetch(`/v1/admin/tenants/${tenant.id}`, {
          method: 'PATCH', body: JSON.stringify({ suspended: !tenant.suspended }),
        });
        Object.assign(tenant, updated);
        bzpToast((updated.suspended ? 'Suspended ' : 'Activated ') + tenant.name);
      } catch (e) { bzpToast('Update failed: ' + e.message); }
    },

    async deleteOne(tenant) {
      if (!confirm(`Delete tenant "${tenant.name}" and all their businesses + runs? Cannot be undone.`)) return;
      try {
        await adminFetch(`/v1/admin/tenants/${tenant.id}`, { method: 'DELETE' });
        this.tenants = this.tenants.filter(t => t.id !== tenant.id);
        bzpToast(`Deleted ${tenant.name}`);
      } catch (e) { bzpToast('Delete failed: ' + e.message); }
    },

    async copyKey(tenant) {
      try {
        await navigator.clipboard.writeText(tenant.api_key);
        bzpToast(`Copied ${tenant.name}'s api_key to clipboard`);
      } catch (e) { bzpToast('Copy failed: ' + e.message); }
    },

    async impersonate(tenant) {
      if (!confirm(`Sign in as "${tenant.name}"? You'll see their dashboard with their data.`)) return;
      try {
        const r = await adminFetch(`/v1/admin/tenants/${tenant.id}/impersonate`, { method: 'POST' });
        bzpSetApiKey(r.api_key);
        bzpSetTenant({ id: r.tenant_id, name: r.name, slug: r.slug, api_key: r.api_key });
        localStorage.setItem(IMPERSONATING_KEY, '1');
        bzpToast(`Signed in as ${r.name}`);
        setTimeout(() => { window.location.href = '/ui/dashboard.html'; }, 400);
      } catch (e) { bzpToast('Impersonate failed: ' + e.message); }
    },

    async dryRunCleanup() {
      if (!this.cleanupPattern) return;
      this.cleanupBusy = true;
      try {
        const r = await adminFetch('/v1/admin/tenants/cleanup', {
          method: 'POST',
          body: JSON.stringify({ pattern: this.cleanupPattern, dry_run: true }),
        });
        this.cleanupPreview = r.matched || [];
        bzpToast(`Found ${this.cleanupPreview.length} match(es) — none deleted yet`);
      } catch (e) { bzpToast('Preview failed: ' + e.message); }
      finally { this.cleanupBusy = false; }
    },

    async confirmAndCleanup() {
      if (!this.cleanupPattern || this.cleanupPreview.length === 0) return;
      const ok = prompt(
        `Type DELETE in capitals to permanently delete ${this.cleanupPreview.length} tenants (cascades to all their businesses + runs):`
      );
      if (ok !== 'DELETE') { bzpToast('Cancelled'); return; }
      this.cleanupBusy = true;
      try {
        const r = await adminFetch('/v1/admin/tenants/cleanup', {
          method: 'POST',
          body: JSON.stringify({
            pattern: this.cleanupPattern,
            dry_run: false,
            confirm_token: 'DELETE',
          }),
        });
        bzpToast(`Deleted ${r.deleted_count} tenant(s)`);
        this.cleanupPreview = [];
        this.cleanupPattern = '';
        await this.load();
      } catch (e) { bzpToast('Delete failed: ' + e.message); }
      finally { this.cleanupBusy = false; }
    },
  }));

  Alpine.data('reportPage', () => ({
    runId: '', run: null, business: null, busy: true, error: '',
    activeTab: 'strategy',
    retrying: false,
    agentTraces() {
      // Look in both places — traces live on RunRecord.agent_traces and on
      // MarketingStrategy.agent_traces (where the runner_service persists them).
      const fromRun = this.run?.agent_traces || [];
      const fromStrategy = this.run?.final_output?.agent_traces || [];
      const seen = new Set();
      const out = [];
      for (const t of [...fromRun, ...fromStrategy]) {
        const k = (t.id || '') + ':' + (t.agent || '');
        if (seen.has(k)) continue;
        seen.add(k);
        out.push(t);
      }
      return out;
    },
    async init() {
      if (!bzpRequireLogin()) return;
      const params = new URLSearchParams(window.location.search);
      this.runId = params.get('run') || '';
      if (!this.runId) { this.error = 'Missing run id in URL'; this.busy = false; return; }
      try {
        this.run = await bzpFetch(`/v1/runs/${this.runId}`);
        if (this.run.business_id) {
          this.business = await bzpFetch(`/v1/businesses/${this.run.business_id}`);
        }
      } catch (e) { this.error = e.message; }
      finally { this.busy = false; }
    },
    async retry() {
      if (!this.run || !this.run.business_id) return;
      this.retrying = true;
      try {
        const newRun = await bzpFetch(`/v1/businesses/${this.run.business_id}/analyze`, {
          method: 'POST',
          body: JSON.stringify({ country: 'IN', state: null }),
        });
        bzpToast('Retry started — opening new run');
        setTimeout(() => {
          window.location.href = `/ui/report.html?run=${newRun.id}`;
        }, 600);
      } catch (e) {
        bzpToast('Retry failed: ' + e.message);
        this.retrying = false;
      }
    },
    statusPill: bzpStatusPill,
    fmtTime: bzpFmtTime,
    fmtCurrency: bzpFmtCurrency,
  }));

});
