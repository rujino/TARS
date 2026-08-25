/**
 * TARS REST API Client Module with JWT Authentication & Persona Configuration
 */
class TARSApiClient {
  constructor(baseUrl = '/api/v1') {
    this.baseUrl = baseUrl;
  }

  getToken() {
    return localStorage.getItem('tars_token');
  }

  setToken(token) {
    localStorage.setItem('tars_token', token);
  }

  clearToken() {
    localStorage.removeItem('tars_token');
    localStorage.removeItem('tars_user');
  }

  getUser() {
    const raw = localStorage.getItem('tars_user');
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  setUser(user) {
    localStorage.setItem('tars_user', JSON.stringify(user));
  }

  async request(endpoint, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    };
    const token = this.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers
    });

    if (res.status === 401) {
      this.clearToken();
      window.dispatchEvent(new CustomEvent('tars:unauthorized'));
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      let errorDetail = `HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        errorDetail = errJson.detail || errJson.message || JSON.stringify(errJson);
      } catch {
        const errText = await res.text();
        if (errText) errorDetail = errText;
      }
      throw new Error(errorDetail);
    }

    return res.json();
  }

  // --- Auth APIs ---
  async signup(username, email, password) {
    const data = await this.request('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ username, email, password })
    });
    if (data && data.access_token) {
      this.setToken(data.access_token);
      if (data.user) this.setUser(data.user);
    }
    return data;
  }

  async login(username, password) {
    const data = await this.request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password })
    });
    if (data && data.access_token) {
      this.setToken(data.access_token);
      if (data.user) this.setUser(data.user);
    }
    return data;
  }

  async getMe() {
    const user = await this.request('/auth/me', { method: 'GET' });
    if (user) this.setUser(user);
    return user;
  }

  // --- TARS Persona Settings APIs ---
  async getConfig() {
    return this.request('/tars/config', { method: 'GET' });
  }

  async updateConfig(config) {
    return this.request('/tars/config', {
      method: 'PATCH',
      body: JSON.stringify(config)
    });
  }

  async resetConfig() {
    return this.request('/tars/config/reset', {
      method: 'POST'
    });
  }
}

if (typeof window !== 'undefined') {
  window.TARSApiClient = TARSApiClient;
}
