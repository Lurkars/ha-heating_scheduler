/**
 * Heating Scheduler card.
 *
 * A self-contained management UI for the heating_scheduler integration:
 * lists all schedules, lets you reorder them (list order = priority, last
 * match wins), and add/edit/delete them through a modal form. Entity
 * pickers and the conditions editor reuse Home Assistant's own
 * <ha-selector> so the UX matches other HA editors (e.g. the
 * automation/blueprint editor) instead of a bespoke checkbox list.
 */

// Same icon set Home Assistant itself uses for these hvac modes.
const MODE_ICONS = { auto: "mdi:thermostat-auto", heat: "mdi:fire", off: "mdi:power" };

const STRINGS = {
  de: {
    cardName: "Heizungsplaner",
    cardDescription: "Verwalte mehrere Heizungs-Zeitpläne mit Thermostaten, Wochentagen, Modus/Temperatur und Bedingungen.",
    title: "Heizungsplaner",
    addSchedule: "+ Neuer Zeitplan",
    empty: "Noch keine Zeitpläne angelegt.",
    moveUp: "Nach oben",
    moveDown: "Nach unten",
    edit: "Bearbeiten",
    duplicate: "Duplizieren",
    copySuffix: "(Kopie)",
    delete: "Löschen",
    enable: "Aktivieren",
    disable: "Deaktivieren",
    conditionNotMet: "Bedingungen nicht erfüllt",
    confirmDelete: (name) => `Zeitplan "${name}" wirklich löschen?`,
    editTitle: "Zeitplan bearbeiten",
    newTitle: "Neuer Zeitplan",
    name: "Name",
    namePlaceholder: "z.B. Werktags Tagsüber",
    thermostats: "Thermostate",
    weekdays: "Wochentage",
    from: "Von",
    to: "Bis",
    mode: "Modus",
    targetTemp: "Zieltemperatur (°C)",
    conditions: "Bedingungen (müssen alle erfüllt sein, sonst wird der Plan ignoriert; zum Ausschließen eine \"Nicht\"-Bedingung verwenden)",
    cancel: "Abbrechen",
    save: "Speichern",
    modeLabels: { auto: "Automatik", heat: "Heizen", off: "Aus" },
    weekdayLabels: ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    errName: "Bitte einen Namen angeben.",
    errEntities: "Bitte mindestens ein Thermostat auswählen.",
    errWeekdays: "Bitte mindestens einen Wochentag auswählen.",
    errTimes: "Bitte Start- und Endzeit angeben.",
    errTemp: "Bitte eine Zieltemperatur angeben.",
  },
  en: {
    cardName: "Heating Scheduler",
    cardDescription: "Manage multiple heating schedules with thermostats, weekdays, mode/temperature and conditions.",
    title: "Heating Scheduler",
    addSchedule: "+ New schedule",
    empty: "No schedules yet.",
    moveUp: "Move up",
    moveDown: "Move down",
    edit: "Edit",
    duplicate: "Duplicate",
    copySuffix: "(copy)",
    delete: "Delete",
    enable: "Enable",
    disable: "Disable",
    conditionNotMet: "Conditions not met",
    confirmDelete: (name) => `Really delete schedule "${name}"?`,
    editTitle: "Edit schedule",
    newTitle: "New schedule",
    name: "Name",
    namePlaceholder: "e.g. Weekdays daytime",
    thermostats: "Thermostats",
    weekdays: "Weekdays",
    from: "From",
    to: "To",
    mode: "Mode",
    targetTemp: "Target temperature (°C)",
    conditions: "Conditions (all must be met, otherwise the schedule is ignored; use a \"Not\" condition to exclude)",
    cancel: "Cancel",
    save: "Save",
    modeLabels: { auto: "Auto", heat: "Heat", off: "Off" },
    weekdayLabels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    errName: "Please enter a name.",
    errEntities: "Please select at least one thermostat.",
    errWeekdays: "Please select at least one weekday.",
    errTimes: "Please enter a start and end time.",
    errTemp: "Please enter a target temperature.",
  },
};

function pickLanguage(candidate) {
  const code = (candidate || "en").toLowerCase().split("-")[0];
  return STRINGS[code] ? code : "en";
}

function getStrings(hass) {
  return STRINGS[pickLanguage(hass && hass.language)];
}

function friendlyName(hass, entityId) {
  const state = hass.states[entityId];
  return (state && state.attributes.friendly_name) || entityId;
}

function emptySchedule() {
  return {
    id: null,
    name: "",
    enabled: true,
    entities: [],
    weekdays: [0, 1, 2, 3, 4, 5, 6],
    time_from: "06:00",
    time_to: "22:00",
    mode: "heat",
    temperature: 21,
    conditions: [],
  };
}

class HeatingSchedulerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._schedules = [];
    this._editing = null;
    this._error = null;
    this._initialized = false;
    this._t = STRINGS.en;
    // Schedule id -> conditions met, pushed by the backend (the card can't
    // evaluate arbitrary automation conditions like templates itself).
    this._conditionStatus = {};
    this._statusSubscription = null;
    this._outsideClickHandler = (ev) => {
      if (!ev.composedPath().includes(this)) this._closeAllMenus();
    };
  }

  connectedCallback() {
    document.addEventListener("click", this._outsideClickHandler);
    this._subscribeStatus();
  }

  disconnectedCallback() {
    document.removeEventListener("click", this._outsideClickHandler);
    this._unsubscribeStatus();
  }

  /**
   * The condition editor's own labels (condition types, and/or/not, the tabs
   * and groups of the "add condition" dialog) live in Home Assistant's
   * "config" translation fragment. That is normally only loaded in the
   * settings panel, not on dashboards, so load it here explicitly. Loading it
   * produces a new hass object whose localize knows the new strings.
   */
  _loadEditorTranslations() {
    if (this._editorTranslationsLoaded || typeof this._hass.loadFragmentTranslation !== "function") return;
    this._editorTranslationsLoaded = true;
    this._hass.loadFragmentTranslation("config").catch(() => {
      this._editorTranslationsLoaded = false;
    });
  }

  _subscribeStatus() {
    if (!this._hass || !this.isConnected || this._statusSubscription) return;
    this._statusSubscription = this._hass.connection.subscribeMessage(
      (msg) => {
        this._conditionStatus = msg.conditions_met || {};
        if (!this._editing) this._render();
      },
      { type: "heating_scheduler/subscribe_status" }
    );
    // Keep the (rejected) promise on failure so we don't retry on every hass update.
    this._statusSubscription.catch(() => {});
  }

  _unsubscribeStatus() {
    if (!this._statusSubscription) return;
    this._statusSubscription.then((unsub) => unsub()).catch(() => {});
    this._statusSubscription = null;
  }

  _closeAllMenus(exceptMenu) {
    this.shadowRoot.querySelectorAll("details.item-menu[open], details.mode-picker[open]").forEach((d) => {
      if (d !== exceptMenu) d.removeAttribute("open");
    });
  }

  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    const previousHass = this._hass;
    this._hass = hass;
    this._t = getStrings(hass);
    if (!this._initialized) {
      this._initialized = true;
      this._loadEditorTranslations();
      this._subscribeStatus();
      this._fetchSchedules();
      return;
    }
    // Open selectors need the current hass, both for live states and for
    // translations loaded after they were mounted.
    if (this._editing) {
      this.shadowRoot.querySelectorAll(".modal ha-selector").forEach((el) => {
        el.hass = hass;
      });
    }
    // Re-render the list live when a scheduled thermostat's current
    // temperature changes (condition status arrives via its own
    // subscription). Skipped while editing so an in-progress form isn't
    // disturbed.
    if (!this._editing && this._relevantStateChanged(previousHass, hass)) {
      this._render();
    }
  }

  _relevantStateChanged(oldHass, newHass) {
    if (!oldHass) return false;
    const climateEntities = new Set();
    for (const schedule of this._schedules) {
      for (const id of schedule.entities || []) climateEntities.add(id);
    }
    for (const id of climateEntities) {
      const oldTemp = oldHass.states[id] && oldHass.states[id].attributes.current_temperature;
      const newTemp = newHass.states[id] && newHass.states[id].attributes.current_temperature;
      if (oldTemp !== newTemp) return true;
    }
    return false;
  }

  _averageCurrentTemperature(schedule) {
    const temps = schedule.entities
      .map((id) => this._hass.states[id] && this._hass.states[id].attributes.current_temperature)
      .filter((t) => typeof t === "number");
    if (temps.length === 0) return null;
    const avg = temps.reduce((sum, t) => sum + t, 0) / temps.length;
    return Math.round(avg * 10) / 10;
  }

  getCardSize() {
    return 2 + (this._schedules ? this._schedules.length : 0);
  }

  async _fetchSchedules() {
    const result = await this._hass.callWS({ type: "heating_scheduler/list" });
    this._schedules = result.schedules || [];
    this._render();
  }

  async _saveSchedule(schedule) {
    try {
      await this._hass.callWS({ type: "heating_scheduler/save", schedule });
      this._editing = null;
      this._error = null;
      await this._fetchSchedules();
    } catch (err) {
      this._error = (err && err.message) || "Failed to save";
      this._render();
    }
  }

  async _deleteSchedule(scheduleId) {
    await this._hass.callWS({ type: "heating_scheduler/delete", schedule_id: scheduleId });
    await this._fetchSchedules();
  }

  async _reorder(order) {
    await this._hass.callWS({ type: "heating_scheduler/reorder", order });
    await this._fetchSchedules();
  }

  _moveSchedule(index, direction) {
    const target = index + direction;
    if (target < 0 || target >= this._schedules.length) return;
    const order = this._schedules.map((s) => s.id);
    const [moved] = order.splice(index, 1);
    order.splice(target, 0, moved);
    this._reorder(order);
  }

  _openEditor(schedule, { duplicate = false } = {}) {
    this._editing = schedule
      ? {
          ...schedule,
          entities: [...schedule.entities],
          weekdays: [...schedule.weekdays],
          // Condition configs are nested objects - deep copy so editing
          // doesn't mutate the listed schedule.
          conditions: JSON.parse(JSON.stringify(schedule.conditions || [])),
        }
      : emptySchedule();
    if (duplicate) {
      this._editing.id = null;
      this._editing.name = `${schedule.name} ${this._t.copySuffix}`;
    }
    // A duplicate is a new, unsaved schedule, so it must be saveable right
    // away even without further changes.
    this._editingSnapshot = duplicate ? null : JSON.stringify(this._editing);
    this._error = null;
    this._render();
  }

  _closeEditor() {
    this._editing = null;
    this._editingSnapshot = null;
    this._error = null;
    this._render();
  }

  _isDirty() {
    return JSON.stringify(this._editing) !== this._editingSnapshot;
  }

  _refreshSaveButton() {
    const btn = this.shadowRoot.querySelector('[data-action="save"]');
    if (btn) btn.disabled = !this._isDirty();
  }

  _handleRootClick(ev) {
    if (ev.target.classList && ev.target.classList.contains("modal-backdrop")) {
      this._closeEditor();
      return;
    }

    const menuEl = ev.target.closest(".item-menu, .mode-picker");
    // Close any other open dropdown - only the one just clicked (if any)
    // stays open.
    this._closeAllMenus(menuEl);

    // Let the native <details>/<summary> menu toggle itself; don't let the
    // click bubble into the row's own "open editor" action underneath it.
    if (ev.target.closest("summary.menu-summary, summary.mode-summary")) return;

    const actionEl = ev.target.closest("[data-action]");

    // A click on blank space inside the open menu dropdown would otherwise
    // fall through to the row's "edit" action underneath it - ignore it.
    if (menuEl && (!actionEl || !menuEl.contains(actionEl))) return;

    if (!actionEl) return;
    const action = actionEl.dataset.action;
    const id = actionEl.dataset.id;
    const t = this._t;

    if (action === "add") {
      this._openEditor(null);
    } else if (action === "edit") {
      this._openEditor(this._schedules.find((s) => s.id === id));
    } else if (action === "duplicate") {
      const schedule = this._schedules.find((s) => s.id === id);
      if (schedule) this._openEditor(schedule, { duplicate: true });
    } else if (action === "delete") {
      const schedule = this._schedules.find((s) => s.id === id);
      if (schedule && confirm(t.confirmDelete(schedule.name))) {
        this._deleteSchedule(id);
      }
    } else if (action === "toggle-enabled") {
      const schedule = this._schedules.find((s) => s.id === id);
      if (schedule) this._saveSchedule({ ...schedule, enabled: !schedule.enabled });
    } else if (action === "move-up") {
      this._moveSchedule(this._schedules.findIndex((s) => s.id === id), -1);
    } else if (action === "move-down") {
      this._moveSchedule(this._schedules.findIndex((s) => s.id === id), 1);
    } else if (action === "close-modal") {
      this._closeEditor();
    } else if (action === "toggle-weekday") {
      const day = Number(actionEl.dataset.day);
      const idx = this._editing.weekdays.indexOf(day);
      if (idx === -1) this._editing.weekdays.push(day);
      else this._editing.weekdays.splice(idx, 1);
      actionEl.classList.toggle("active");
      this._refreshSaveButton();
    } else if (action === "select-mode") {
      const mode = actionEl.dataset.mode;
      const modePicker = actionEl.closest(".mode-picker");
      this._editing.mode = mode;
      modePicker
        .querySelectorAll(".mode-option")
        .forEach((btn) => btn.classList.toggle("active", btn === actionEl));
      const summary = modePicker.querySelector(".mode-summary");
      summary.querySelector("ha-icon").setAttribute("icon", MODE_ICONS[mode]);
      summary.querySelector("span").textContent = t.modeLabels[mode];
      modePicker.removeAttribute("open");
      if (this._tempSelectorEl) this._tempSelectorEl.disabled = mode === "off";
      this._refreshSaveButton();
    } else if (action === "save") {
      this._handleSave();
    }
  }

  _handleSave() {
    const t = this._t;
    const name = (this._editing.name || "").trim();
    const timeFrom = this._editing.time_from;
    const timeTo = this._editing.time_to;
    const mode = this._editing.mode;
    const temperature = mode === "off" ? null : this._editing.temperature;

    this._editing = { ...this._editing, name, temperature };

    if (!name) {
      this._error = t.errName;
      this._render();
      return;
    }
    if (this._editing.entities.length === 0) {
      this._error = t.errEntities;
      this._render();
      return;
    }
    if (this._editing.weekdays.length === 0) {
      this._error = t.errWeekdays;
      this._render();
      return;
    }
    if (!timeFrom || !timeTo) {
      this._error = t.errTimes;
      this._render();
      return;
    }
    if (mode !== "off" && (temperature === null || Number.isNaN(temperature))) {
      this._error = t.errTemp;
      this._render();
      return;
    }

    const schedule = {
      id: this._editing.id || undefined,
      name,
      enabled: this._editing.enabled,
      entities: this._editing.entities,
      weekdays: this._editing.weekdays,
      time_from: timeFrom,
      time_to: timeTo,
      mode,
      temperature,
      conditions: this._editing.conditions,
    };

    this._saveSchedule(schedule);
  }

  _render() {
    if (!this._hass) return;
    const t = this._t;
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>${this._styles()}</style>
      <ha-card>
        <div class="header">
          <div class="title">${t.title}</div>
          <button class="btn btn-filled" data-action="add">${t.addSchedule}</button>
        </div>
        <div class="content">
          ${this._schedules.length === 0 ? `<div class="empty">${t.empty}</div>` : this._renderList()}
        </div>
      </ha-card>
      ${this._editing ? this._renderModal() : ""}
    `;

    root.removeEventListener("click", this._boundClick);
    this._boundClick = (ev) => this._handleRootClick(ev);
    root.addEventListener("click", this._boundClick);

    if (this._editing) {
      this._mountSelectors();
      this._refreshSaveButton();
    }
  }

  _renderList() {
    return `
      <div class="schedule-list">
        ${this._schedules.map((s, i) => this._renderRow(s, i)).join("")}
      </div>
    `;
  }

  _renderRow(schedule, index) {
    const t = this._t;
    const days = schedule.weekdays
      .slice()
      .sort((a, b) => a - b)
      .map((d) => t.weekdayLabels[d])
      .join(" ");
    const entityNames = schedule.entities.map((e) => friendlyName(this._hass, e)).join(", ");
    const meta = schedule.mode === "off"
      ? `${days} · ${schedule.time_from}–${schedule.time_to}`
      : `${days} · ${schedule.time_from}–${schedule.time_to} · ${schedule.temperature} °C`;

    const showBlocked = schedule.enabled && this._conditionStatus[schedule.id] === false;
    const avgTemp = this._averageCurrentTemperature(schedule);

    return `
      <div class="schedule-item ${schedule.enabled ? "" : "disabled-row"} ${showBlocked ? "condition-blocked" : ""}" data-action="edit" data-id="${schedule.id}">
        <ha-icon class="mode-icon mode-${schedule.mode}" icon="${MODE_ICONS[schedule.mode] || "mdi:thermostat"}"></ha-icon>
        <div class="schedule-info">
          <div class="schedule-name" ${showBlocked ? `title="${t.conditionNotMet}"` : ""}>${schedule.name}</div>
          <div class="schedule-meta">${meta}</div>
        </div>
        <div class="thermostats" title="${entityNames}">
          <ha-icon icon="mdi:thermostat"></ha-icon>
          <span>${schedule.entities.length}</span>
          ${avgTemp !== null ? `<span class="current-temp">${avgTemp} °C</span>` : ""}
        </div>
        <details class="item-menu">
          <summary class="menu-summary" title="${t.edit}/${t.delete}">
            <ha-icon icon="mdi:dots-vertical"></ha-icon>
          </summary>
          <div class="menu-items">
            <button data-action="toggle-enabled" data-id="${schedule.id}">
              <ha-icon icon="${schedule.enabled ? "mdi:toggle-switch-off-outline" : "mdi:toggle-switch"}"></ha-icon>${schedule.enabled ? t.disable : t.enable}
            </button>
            <button data-action="move-up" data-id="${schedule.id}" ${index === 0 ? "disabled" : ""}>
              <ha-icon icon="mdi:arrow-up"></ha-icon>${t.moveUp}
            </button>
            <button data-action="move-down" data-id="${schedule.id}" ${index === this._schedules.length - 1 ? "disabled" : ""}>
              <ha-icon icon="mdi:arrow-down"></ha-icon>${t.moveDown}
            </button>
            <button data-action="duplicate" data-id="${schedule.id}">
              <ha-icon icon="mdi:content-copy"></ha-icon>${t.duplicate}
            </button>
            <button data-action="delete" data-id="${schedule.id}" class="danger">
              <ha-icon icon="mdi:delete"></ha-icon>${t.delete}
            </button>
          </div>
        </details>
      </div>
    `;
  }

  _renderModal() {
    const t = this._t;
    const e = this._editing;

    return `
      <div class="modal-backdrop">
        <div class="modal">
          <div class="modal-header">
            <div class="title">${e.id ? t.editTitle : t.newTitle}</div>
            <ha-icon-button data-action="close-modal" label="${t.cancel}">
              <ha-icon icon="mdi:close"></ha-icon>
            </ha-icon-button>
          </div>
          <div class="modal-body">
            ${this._error ? `<div class="error">${this._error}</div>` : ""}

            <div class="field">
              <span>${t.name}</span>
              <div id="name-picker"></div>
            </div>

            <div class="field">
              <span>${t.thermostats}</span>
              <div id="entities-picker"></div>
            </div>

            <div class="field">
              <span>${t.weekdays}</span>
              <div class="weekday-picker">
                ${t.weekdayLabels.map((label, day) => `
                  <button type="button" class="weekday-toggle ${e.weekdays.includes(day) ? "active" : ""}" data-action="toggle-weekday" data-day="${day}">${label}</button>
                `).join("")}
              </div>
            </div>

            <div class="field-row">
              <div class="field">
                <span>${t.from}</span>
                <div id="from-picker"></div>
              </div>
              <div class="field">
                <span>${t.to}</span>
                <div id="to-picker"></div>
              </div>
            </div>

            <div class="field-row">
              <div class="field">
                <span>${t.mode}</span>
                <details class="mode-picker">
                  <summary class="mode-summary">
                    <ha-icon icon="${MODE_ICONS[e.mode]}"></ha-icon>
                    <span>${t.modeLabels[e.mode]}</span>
                    <ha-icon class="mode-chevron" icon="mdi:chevron-down"></ha-icon>
                  </summary>
                  <div class="mode-options">
                    ${Object.entries(t.modeLabels).map(([value, label]) => `
                      <button type="button" class="mode-option ${e.mode === value ? "active" : ""}" data-action="select-mode" data-mode="${value}">
                        <ha-icon icon="${MODE_ICONS[value]}"></ha-icon>
                        <span>${label}</span>
                      </button>
                    `).join("")}
                  </div>
                </details>
              </div>
              <div class="field">
                <span>${t.targetTemp}</span>
                <div id="temp-picker"></div>
              </div>
            </div>

            <div class="field">
              <span>${t.conditions}</span>
              <div id="conditions-picker"></div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-text" data-action="close-modal">${t.cancel}</button>
            <button class="btn btn-filled" data-action="save" disabled>${t.save}</button>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Mount Home Assistant's own <ha-selector> pickers into the modal for
   * the thermostat and condition fields, instead of a bespoke checkbox
   * list, so the UX matches the rest of Home Assistant (e.g. the
   * automation/blueprint editor). ha-selector is part of a lazily loaded
   * frontend chunk, so wait for it to be defined if it isn't yet (it almost
   * always already is, since the user has to be in dashboard-edit mode to
   * reach this dialog in the first place).
   */
  async _mountSelectors() {
    if (!customElements.get("ha-selector")) {
      try {
        await customElements.whenDefined("ha-selector");
      } catch (err) {
        return;
      }
    }
    // The modal may have been closed (or re-rendered) while we were waiting.
    if (!this._editing) return;
    const root = this.shadowRoot;

    const nameContainer = root.getElementById("name-picker");
    if (nameContainer && !nameContainer.firstChild) {
      nameContainer.appendChild(
        this._createTextSelector({
          value: this._editing.name,
          placeholder: this._t.namePlaceholder,
          onChange: (value) => {
            this._editing.name = value;
          },
        })
      );
    }

    const fromContainer = root.getElementById("from-picker");
    if (fromContainer && !fromContainer.firstChild) {
      fromContainer.appendChild(
        this._createTimeSelector({
          value: this._editing.time_from,
          onChange: (value) => {
            this._editing.time_from = value;
          },
        })
      );
    }

    const toContainer = root.getElementById("to-picker");
    if (toContainer && !toContainer.firstChild) {
      toContainer.appendChild(
        this._createTimeSelector({
          value: this._editing.time_to,
          onChange: (value) => {
            this._editing.time_to = value;
          },
        })
      );
    }

    const entitiesContainer = root.getElementById("entities-picker");
    if (entitiesContainer && !entitiesContainer.firstChild) {
      entitiesContainer.appendChild(
        this._createEntitySelector({
          value: this._editing.entities,
          domains: ["climate"],
          onChange: (value) => {
            this._editing.entities = value;
          },
        })
      );
    }

    const conditionsContainer = root.getElementById("conditions-picker");
    if (conditionsContainer && !conditionsContainer.firstChild) {
      conditionsContainer.appendChild(
        this._createConditionSelector({
          value: this._editing.conditions,
          onChange: (value) => {
            this._editing.conditions = value;
          },
        })
      );
    }

    const tempContainer = root.getElementById("temp-picker");
    if (tempContainer && !tempContainer.firstChild) {
      this._tempSelectorEl = this._createNumberSelector({
        value: this._editing.temperature ?? 21,
        disabled: this._editing.mode === "off",
        onChange: (value) => {
          this._editing.temperature = value;
        },
      });
      tempContainer.appendChild(this._tempSelectorEl);
    }
  }

  // All selector value-changed handlers funnel through this so the Save
  // button's disabled state stays in sync without touching every call site.
  _onSelectorChange(onChange, value) {
    onChange(value);
    this._refreshSaveButton();
  }

  _createTextSelector({ value, placeholder, onChange }) {
    const el = document.createElement("ha-selector");
    el.hass = this._hass;
    el.selector = { text: {} };
    el.value = value;
    if (placeholder) el.placeholder = placeholder;
    el.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const newValue = ev.detail.value || "";
      el.value = newValue; // keep the widget's own display in sync
      this._onSelectorChange(onChange, newValue);
    });
    return el;
  }

  _createTimeSelector({ value, onChange }) {
    const el = document.createElement("ha-selector");
    el.hass = this._hass;
    el.selector = { time: {} };
    // The time selector works with "HH:MM:SS"; schedules only store "HH:MM".
    el.value = `${value}:00`;
    el.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const raw = ev.detail.value || "00:00:00";
      el.value = raw; // keep the widget's own display in sync
      this._onSelectorChange(onChange, raw.slice(0, 5));
    });
    return el;
  }

  _createEntitySelector({ value, domains, onChange }) {
    const el = document.createElement("ha-selector");
    el.hass = this._hass;
    el.selector = { entity: { multiple: true, filter: domains.map((domain) => ({ domain })) } };
    el.value = value;
    el.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const newValue = ev.detail.value || [];
      el.value = newValue; // keep the widget's own display in sync
      this._onSelectorChange(onChange, newValue);
    });
    return el;
  }

  // The same condition editor as in automations/blueprints, storing the
  // condition configs in exactly the format automations use.
  _createConditionSelector({ value, onChange }) {
    const el = document.createElement("ha-selector");
    el.hass = this._hass;
    el.selector = { condition: {} };
    el.value = value;
    el.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const newValue = ev.detail.value || [];
      el.value = newValue; // keep the widget's own display in sync
      this._onSelectorChange(onChange, newValue);
    });
    return el;
  }

  _createNumberSelector({ value, disabled, onChange }) {
    const el = document.createElement("ha-selector");
    el.hass = this._hass;
    el.selector = { number: { min: 5, max: 35, step: 0.5, mode: "box", unit_of_measurement: "°C" } };
    el.value = value;
    el.disabled = disabled;
    el.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const newValue = ev.detail.value;
      el.value = newValue; // keep the widget's own display in sync
      this._onSelectorChange(onChange, newValue);
    });
    return el;
  }

  _styles() {
    return `
      ha-card { padding: 0; }
      .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 16px 0 16px;
      }
      .title { font-size: 1.2em; font-weight: 500; color: var(--primary-text-color); }
      .content { padding: 8px 16px 16px; }
      .empty { color: var(--secondary-text-color); padding: 8px 0; }

      .schedule-list { display: flex; flex-direction: column; }
      .schedule-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 4px;
        border-bottom: 1px solid var(--divider-color);
        cursor: pointer;
      }
      .schedule-item:last-child { border-bottom: none; }
      .schedule-item:hover { background: var(--secondary-background-color, rgba(0,0,0,0.03)); }
      .schedule-item.disabled-row { opacity: 0.45; }

      .mode-icon { flex: none; color: var(--secondary-text-color); }
      .mode-icon.mode-heat { color: var(--state-active-color, #ff8100); }
      .mode-icon.mode-auto { color: var(--primary-color); }

      .schedule-info { flex: 1; min-width: 0; }
      .schedule-name {
        font-weight: 500; color: var(--primary-text-color);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      }
      .schedule-item.condition-blocked .schedule-name { color: var(--secondary-text-color); }
      .schedule-item.condition-blocked .mode-icon.mode-heat,
      .schedule-item.condition-blocked .mode-icon.mode-auto {
        color: var(--disabled-text-color, #bdbdbd);
      }
      .schedule-meta {
        font-size: 0.85em; color: var(--secondary-text-color);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      }

      .thermostats {
        flex: none; display: flex; align-items: center; gap: 3px;
        color: var(--secondary-text-color); font-size: 0.85em;
      }
      .thermostats ha-icon { --mdc-icon-size: 18px; }
      .current-temp { margin-left: 2px; }

      .item-menu { flex: none; position: relative; }
      .item-menu > summary { list-style: none; cursor: pointer; }
      .item-menu > summary::-webkit-details-marker { display: none; }
      .menu-summary {
        display: flex; align-items: center; justify-content: center;
        width: 32px; height: 32px; border-radius: 50%; color: var(--secondary-text-color);
      }
      .menu-summary:hover { background: rgba(var(--rgb-primary-text-color, 0,0,0), 0.08); }
      .item-menu[open] .menu-summary { color: var(--primary-color); }
      .menu-items {
        position: absolute; right: 0; top: 36px; z-index: 5;
        background: var(--card-background-color, white);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.2));
        display: flex; flex-direction: column; min-width: 160px; overflow: hidden;
      }
      .menu-items button {
        display: flex; align-items: center; gap: 8px;
        background: none; border: none; cursor: pointer;
        padding: 10px 14px; font-size: 0.9em; color: var(--primary-text-color);
        text-align: left;
      }
      .menu-items button:hover { background: var(--secondary-background-color, rgba(0,0,0,0.05)); }
      .menu-items button:disabled { opacity: 0.35; cursor: default; }
      .menu-items button:disabled:hover { background: none; }
      .menu-items button.danger { color: var(--error-color, #db4437); }
      .menu-items ha-icon { --mdc-icon-size: 18px; }

      .modal-backdrop {
        position: fixed; inset: 0; background: rgba(0,0,0,0.5);
        display: flex; align-items: center; justify-content: center; z-index: 10;
      }
      .modal {
        background: var(--card-background-color, white);
        color: var(--primary-text-color);
        border-radius: var(--ha-card-border-radius, 8px);
        width: min(560px, 92vw);
        max-height: 88vh;
        display: flex;
        flex-direction: column;
      }
      .modal-header {
        display: flex; justify-content: space-between; align-items: center;
        padding: 16px; border-bottom: 1px solid var(--divider-color);
      }
      .modal-header .title { font-size: 1.1em; font-weight: 500; }
      .modal-body { padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
      .modal-footer {
        display: flex; justify-content: flex-end; gap: 8px;
        padding: 12px 16px; border-top: 1px solid var(--divider-color);
      }
      .field { display: flex; flex-direction: column; gap: 4px; font-size: 0.9em; color: var(--secondary-text-color); flex: 1; }
      .field-row { display: flex; gap: 12px; }
      .weekday-picker { display: flex; gap: 6px; }
      .weekday-toggle {
        flex: 1; padding: 8px 0; border-radius: 4px; border: 1px solid var(--divider-color);
        background: var(--card-background-color, white); color: var(--primary-text-color); cursor: pointer;
      }
      .weekday-toggle.active { background: var(--primary-color); color: var(--text-primary-color, white); border-color: var(--primary-color); }

      .mode-picker { position: relative; }
      .mode-picker > summary { list-style: none; cursor: pointer; }
      .mode-picker > summary::-webkit-details-marker { display: none; }
      .mode-summary {
        display: flex; align-items: center; gap: 8px;
        padding: 8px 10px; border-radius: 4px; border: 1px solid var(--divider-color);
        background: var(--card-background-color, white); color: var(--primary-text-color);
        font-size: 1em;
      }
      .mode-summary ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
      .mode-summary span { flex: 1; }
      .mode-chevron { transition: transform 0.2s; }
      .mode-picker[open] .mode-chevron { transform: rotate(180deg); }
      .mode-options {
        position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 5;
        background: var(--card-background-color, white);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.2));
        display: flex; flex-direction: column; overflow: hidden;
      }
      .mode-option {
        display: flex; align-items: center; gap: 8px;
        padding: 10px 12px; border: none; background: none; color: var(--primary-text-color);
        cursor: pointer; font: inherit; font-size: 0.9em; text-align: left;
      }
      .mode-option:hover { background: var(--secondary-background-color, rgba(0,0,0,0.05)); }
      .mode-option ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
      .mode-option.active { color: var(--primary-color); }
      .mode-option.active ha-icon { color: var(--primary-color); }
      .error {
        background: rgba(var(--rgb-error-color, 219,68,55), 0.1);
        color: var(--error-color, #db4437);
        padding: 8px 12px; border-radius: 4px; font-size: 0.9em;
      }

      .btn {
        border: none; cursor: pointer; font: inherit; font-weight: 500; font-size: 0.9em;
        height: 36px; padding: 0 16px; border-radius: 18px;
        display: inline-flex; align-items: center; justify-content: center;
      }
      .btn-text { background: transparent; color: var(--primary-color); padding: 0 12px; }
      .btn-text:hover { background: rgba(var(--rgb-primary-color, 3,169,244), 0.08); }
      .btn-filled { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .btn-filled:hover { filter: brightness(1.08); }
      .btn-filled:disabled {
        background: rgba(var(--rgb-primary-text-color, 0,0,0), 0.12);
        color: rgba(var(--rgb-primary-text-color, 0,0,0), 0.38);
        cursor: default;
      }
    `;
  }
}

customElements.define("heating-scheduler-card", HeatingSchedulerCard);

const moduleStrings = STRINGS[pickLanguage(document.documentElement.lang)];
window.customCards = window.customCards || [];
window.customCards.push({
  type: "heating-scheduler-card",
  name: moduleStrings.cardName,
  description: moduleStrings.cardDescription,
});
