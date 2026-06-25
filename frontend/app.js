/**
 * NLP-to-SQL Assistant — Frontend Application
 *
 * Handles query submission, result rendering (paginated, sortable table),
 * feedback collection, and UI state management.
 */

(function () {
    'use strict';

    // =========================================================================
    // Configuration
    // =========================================================================

    // API base URL — auto-detects based on where frontend is served from
    // If served separately (e.g., python -m http.server 3000), point to API
    const API_BASE = window.location.port === '8000'
        ? '/api/v1'
        : 'http://localhost:8000/api/v1';
    const ROWS_PER_PAGE = 25;

    // Auth token for local dev (set via the settings panel)
    let authToken = localStorage.getItem('nlp_sql_auth_token') || 'dev-token';

    // =========================================================================
    // DOM References
    // =========================================================================

    const queryForm = document.getElementById('queryForm');
    const queryInput = document.getElementById('queryInput');
    const sendBtn = document.getElementById('sendBtn');
    const messagesArea = document.getElementById('messagesArea');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const settingsToggle = document.getElementById('settingsToggle');
    const settingsPanel = document.getElementById('settingsPanel');
    const apiUrlInput = document.getElementById('apiUrlInput');
    const authTokenInput = document.getElementById('authTokenInput');
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');
    const connectionStatus = document.getElementById('connectionStatus');

    // =========================================================================
    // State
    // =========================================================================

    let isLoading = false;

    // =========================================================================
    // Event Listeners
    // =========================================================================

    queryForm.addEventListener('submit', function (e) {
        e.preventDefault();
        submitQuery();
    });

    // Settings panel toggle
    settingsToggle.addEventListener('click', function () {
        const isHidden = settingsPanel.hidden;
        settingsPanel.hidden = !isHidden;
        settingsToggle.setAttribute('aria-expanded', String(isHidden));
    });

    // Save settings
    saveSettingsBtn.addEventListener('click', async function () {
        const newUrl = apiUrlInput.value.trim();
        const newToken = authTokenInput.value.trim();

        if (newUrl) {
            localStorage.setItem('nlp_sql_api_base', newUrl);
            // Update the API_BASE variable dynamically
            window._apiBase = newUrl;
        }
        if (newToken) {
            authToken = newToken;
            localStorage.setItem('nlp_sql_auth_token', newToken);
        }

        // Test connection
        connectionStatus.textContent = 'Testing...';
        connectionStatus.className = 'connection-status';
        try {
            const testUrl = (window._apiBase || API_BASE).replace('/api/v1', '') + '/api/v1/health';
            const resp = await fetch(testUrl);
            if (resp.ok) {
                connectionStatus.textContent = '✓ Connected!';
                connectionStatus.className = 'connection-status success';
            } else {
                connectionStatus.textContent = `✗ Error ${resp.status}`;
                connectionStatus.className = 'connection-status error';
            }
        } catch (err) {
            connectionStatus.textContent = '✗ Cannot connect';
            connectionStatus.className = 'connection-status error';
        }
    });

    // Load saved settings on startup
    const savedUrl = localStorage.getItem('nlp_sql_api_base');
    const savedToken = localStorage.getItem('nlp_sql_auth_token');
    if (savedUrl) {
        apiUrlInput.value = savedUrl;
        window._apiBase = savedUrl;
    }
    if (savedToken) {
        authTokenInput.value = savedToken;
        authToken = savedToken;
    }

    /** Get the effective API base URL */
    function getApiBase() {
        return window._apiBase || API_BASE;
    }

    // =========================================================================
    // Core Functions
    // =========================================================================

    /**
     * Submit the natural language query to the API.
     */
    async function submitQuery() {
        const query = queryInput.value.trim();
        if (!query || isLoading) return;

        setLoading(true);
        clearWelcomeMessage();

        try {
            const response = await fetch(`${getApiBase()}/query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify({ nl_query: query })
            });

            const data = await response.json();

            if (!response.ok) {
                const errorMsg = data.detail || data.message || `Error: ${response.status} ${response.statusText}`;
                renderError(query, errorMsg);
                return;
            }

            // Handle clarification response
            if (data.clarification_prompt) {
                renderClarification(query, data.clarification_prompt);
                return;
            }

            // Render successful results
            renderResults(query, data);

        } catch (err) {
            renderError(query, 'Unable to connect to the server. Please check your connection and try again.');
        } finally {
            setLoading(false);
            queryInput.value = '';
            queryInput.focus();
        }
    }

    /**
     * Render query results with a paginated, sortable table.
     * @param {string} query - The user's original NL query
     * @param {object} data - Response from the API
     */
    function renderResults(query, data) {
        const block = document.createElement('div');
        block.className = 'message-block';
        block.setAttribute('role', 'region');
        block.setAttribute('aria-label', 'Query result');

        // User query display
        const queryEl = document.createElement('p');
        queryEl.className = 'user-query';
        queryEl.textContent = query;
        block.appendChild(queryEl);

        // Cache badge
        if (data.cache_hit) {
            const badge = document.createElement('span');
            badge.className = 'cache-badge';
            badge.textContent = 'Served from cache';
            badge.setAttribute('aria-label', 'Result served from semantic cache');
            block.appendChild(badge);
        }

        // NL Summary (from Azure OpenAI result summarization)
        if (data.summary) {
            const summaryEl = document.createElement('div');
            summaryEl.className = 'result-summary';
            summaryEl.textContent = data.summary;
            block.appendChild(summaryEl);
        }

        // Visualization suggestion
        if (data.visualization_suggestion && data.visualization_suggestion.type !== 'table') {
            const vizEl = document.createElement('span');
            vizEl.className = 'viz-suggestion';
            const icons = { bar: '📊', line: '📈', pie: '🥧' };
            vizEl.textContent = `${icons[data.visualization_suggestion.type] || '📊'} Suggested: ${data.visualization_suggestion.type} chart — ${data.visualization_suggestion.reason}`;
            block.appendChild(vizEl);
        }

        // SQL collapsible block
        if (data.sql) {
            block.appendChild(createSqlBlock(data.sql));
        }

        // Results table
        if (data.rows && data.rows.length > 0) {
            const columns = data.columns || Object.keys(data.rows[0]).map(name => ({ name, data_type: 'string' }));
            const tableState = {
                rows: data.rows,
                columns: columns,
                currentPage: 1,
                sortColumn: null,
                sortDirection: 'asc',
                totalPages: Math.ceil(data.rows.length / ROWS_PER_PAGE)
            };

            const tableContainer = document.createElement('div');
            tableContainer.className = 'results-table-container';
            block.appendChild(tableContainer);

            const rowInfo = document.createElement('p');
            rowInfo.className = 'row-info';
            const truncatedNote = data.truncated ? ' (results truncated by row cap)' : '';
            rowInfo.textContent = `${data.row_count || data.rows.length} row(s) returned${truncatedNote}`;
            block.appendChild(rowInfo);

            const paginationContainer = document.createElement('nav');
            paginationContainer.className = 'pagination';
            paginationContainer.setAttribute('aria-label', 'Results pagination');
            block.appendChild(paginationContainer);

            renderTable(tableContainer, paginationContainer, tableState);
        } else {
            const noData = document.createElement('p');
            noData.className = 'row-info';
            noData.textContent = 'Query executed successfully. No rows returned.';
            block.appendChild(noData);
        }

        // Feedback controls
        block.appendChild(createFeedbackControls(data.trace_id, query, data.sql));

        messagesArea.appendChild(block);
        scrollToBottom();
    }

    /**
     * Render a table with sorting and pagination support.
     */
    function renderTable(container, paginationContainer, state) {
        const sortedRows = getSortedRows(state);
        const start = (state.currentPage - 1) * ROWS_PER_PAGE;
        const pageRows = sortedRows.slice(start, start + ROWS_PER_PAGE);

        // Build table
        const table = document.createElement('table');
        table.className = 'results-table';
        table.setAttribute('role', 'grid');

        // Header
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        state.columns.forEach(col => {
            const th = document.createElement('th');
            th.setAttribute('scope', 'col');
            th.setAttribute('tabindex', '0');
            th.setAttribute('role', 'columnheader');

            let sortLabel = 'none';
            if (state.sortColumn === col.name) {
                sortLabel = state.sortDirection === 'asc' ? 'ascending' : 'descending';
            }
            th.setAttribute('aria-sort', sortLabel);

            th.innerHTML = `${escapeHtml(col.name)}<span class="sort-indicator" aria-hidden="true"></span>`;

            th.addEventListener('click', () => {
                handleSort(container, paginationContainer, state, col.name);
            });
            th.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleSort(container, paginationContainer, state, col.name);
                }
            });

            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Body
        const tbody = document.createElement('tbody');
        pageRows.forEach(row => {
            const tr = document.createElement('tr');
            state.columns.forEach(col => {
                const td = document.createElement('td');
                const value = row[col.name];
                td.textContent = value !== null && value !== undefined ? String(value) : '';
                td.setAttribute('title', td.textContent);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);

        container.innerHTML = '';
        container.appendChild(table);

        // Pagination
        renderPagination(paginationContainer, container, state);
    }

    /**
     * Handle column sort click.
     */
    function handleSort(container, paginationContainer, state, columnName) {
        if (state.sortColumn === columnName) {
            state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            state.sortColumn = columnName;
            state.sortDirection = 'asc';
        }
        state.currentPage = 1;
        renderTable(container, paginationContainer, state);
    }

    /**
     * Sort rows based on current state.
     */
    function getSortedRows(state) {
        if (!state.sortColumn) return [...state.rows];

        return [...state.rows].sort((a, b) => {
            const aVal = a[state.sortColumn];
            const bVal = b[state.sortColumn];

            if (aVal === null || aVal === undefined) return 1;
            if (bVal === null || bVal === undefined) return -1;

            let comparison = 0;
            if (typeof aVal === 'number' && typeof bVal === 'number') {
                comparison = aVal - bVal;
            } else {
                comparison = String(aVal).localeCompare(String(bVal), undefined, { numeric: true });
            }

            return state.sortDirection === 'asc' ? comparison : -comparison;
        });
    }

    /**
     * Render pagination controls.
     */
    function renderPagination(paginationContainer, tableContainer, state) {
        paginationContainer.innerHTML = '';

        if (state.totalPages <= 1) return;

        // Previous button
        const prevBtn = createPaginationBtn('← Prev', state.currentPage <= 1);
        prevBtn.addEventListener('click', () => {
            if (state.currentPage > 1) {
                state.currentPage--;
                renderTable(tableContainer, paginationContainer, state);
            }
        });
        paginationContainer.appendChild(prevBtn);

        // Page numbers
        const pages = getPageNumbers(state.currentPage, state.totalPages);
        pages.forEach(page => {
            if (page === '...') {
                const ellipsis = document.createElement('span');
                ellipsis.className = 'pagination-info';
                ellipsis.textContent = '…';
                ellipsis.setAttribute('aria-hidden', 'true');
                paginationContainer.appendChild(ellipsis);
            } else {
                const pageBtn = createPaginationBtn(String(page), false);
                if (page === state.currentPage) {
                    pageBtn.classList.add('active');
                    pageBtn.setAttribute('aria-current', 'page');
                }
                pageBtn.addEventListener('click', () => {
                    state.currentPage = page;
                    renderTable(tableContainer, paginationContainer, state);
                });
                paginationContainer.appendChild(pageBtn);
            }
        });

        // Next button
        const nextBtn = createPaginationBtn('Next →', state.currentPage >= state.totalPages);
        nextBtn.addEventListener('click', () => {
            if (state.currentPage < state.totalPages) {
                state.currentPage++;
                renderTable(tableContainer, paginationContainer, state);
            }
        });
        paginationContainer.appendChild(nextBtn);
    }

    /**
     * Generate page number array with ellipsis.
     */
    function getPageNumbers(current, total) {
        if (total <= 7) {
            return Array.from({ length: total }, (_, i) => i + 1);
        }

        const pages = [];
        pages.push(1);

        if (current > 3) pages.push('...');

        const start = Math.max(2, current - 1);
        const end = Math.min(total - 1, current + 1);

        for (let i = start; i <= end; i++) {
            pages.push(i);
        }

        if (current < total - 2) pages.push('...');

        pages.push(total);
        return pages;
    }

    /**
     * Create a pagination button element.
     */
    function createPaginationBtn(label, disabled) {
        const btn = document.createElement('button');
        btn.textContent = label;
        btn.disabled = disabled;
        btn.setAttribute('aria-label', `Page ${label}`);
        return btn;
    }

    // =========================================================================
    // SQL Block
    // =========================================================================

    /**
     * Create a collapsible SQL code block (collapsed by default).
     */
    function createSqlBlock(sql) {
        const wrapper = document.createElement('div');
        wrapper.className = 'sql-block';

        const toggle = document.createElement('button');
        toggle.className = 'sql-toggle';
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', `sql-${Date.now()}`);
        toggle.innerHTML = '<span class="arrow" aria-hidden="true">▶</span> Show generated SQL';

        const content = document.createElement('pre');
        content.className = 'sql-content';
        content.id = toggle.getAttribute('aria-controls');
        content.setAttribute('role', 'region');
        content.setAttribute('aria-label', 'Generated SQL query');
        content.hidden = true;

        const code = document.createElement('code');
        code.textContent = sql;
        content.appendChild(code);

        toggle.addEventListener('click', () => {
            toggleSqlBlock(toggle, content);
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(content);
        return wrapper;
    }

    /**
     * Toggle SQL block visibility.
     */
    function toggleSqlBlock(toggle, content) {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        content.hidden = expanded;
        toggle.innerHTML = expanded
            ? '<span class="arrow" aria-hidden="true">▶</span> Show generated SQL'
            : '<span class="arrow" aria-hidden="true">▶</span> Hide generated SQL';
    }

    // =========================================================================
    // Feedback
    // =========================================================================

    /**
     * Create thumbs up/down feedback controls.
     */
    function createFeedbackControls(traceId, nlQuery, sql) {
        const wrapper = document.createElement('div');
        wrapper.className = 'feedback-controls';
        wrapper.setAttribute('role', 'group');
        wrapper.setAttribute('aria-label', 'Result feedback');

        const label = document.createElement('span');
        label.className = 'feedback-label';
        label.textContent = 'Was this helpful?';
        wrapper.appendChild(label);

        const thumbsUp = document.createElement('button');
        thumbsUp.className = 'feedback-btn';
        thumbsUp.textContent = '👍';
        thumbsUp.setAttribute('aria-label', 'Thumbs up — this result was helpful');
        thumbsUp.setAttribute('aria-pressed', 'false');

        const thumbsDown = document.createElement('button');
        thumbsDown.className = 'feedback-btn';
        thumbsDown.textContent = '👎';
        thumbsDown.setAttribute('aria-label', 'Thumbs down — this result was not helpful');
        thumbsDown.setAttribute('aria-pressed', 'false');

        thumbsUp.addEventListener('click', () => {
            submitFeedback('thumbs_up', traceId, nlQuery, sql);
            thumbsUp.setAttribute('aria-pressed', 'true');
            thumbsUp.classList.add('selected');
            thumbsDown.disabled = true;
            showFeedbackThanks(wrapper);
        });

        thumbsDown.addEventListener('click', () => {
            submitFeedback('thumbs_down', traceId, nlQuery, sql);
            thumbsDown.setAttribute('aria-pressed', 'true');
            thumbsDown.classList.add('selected');
            thumbsUp.disabled = true;
            showFeedbackThanks(wrapper);
        });

        wrapper.appendChild(thumbsUp);
        wrapper.appendChild(thumbsDown);
        return wrapper;
    }

    /**
     * Submit feedback to the API.
     * @param {string} rating - 'thumbs_up' or 'thumbs_down'
     * @param {string} traceId - Trace ID from the query response
     * @param {string} nlQuery - Original natural language query
     * @param {string} sql - Generated SQL
     */
    async function submitFeedback(rating, traceId, nlQuery, sql) {
        try {
            await fetch(`${getApiBase()}/feedback`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify({
                    rating: rating,
                    nl_query: nlQuery,
                    generated_sql: sql,
                    trace_id: traceId || ''
                })
            });
        } catch (err) {
            // Feedback submission is non-critical; silently fail
            console.warn('Feedback submission failed:', err);
        }
    }

    /**
     * Show "Thanks for your feedback" message.
     */
    function showFeedbackThanks(wrapper) {
        const thanks = document.createElement('span');
        thanks.className = 'feedback-thanks';
        thanks.textContent = 'Thanks for your feedback!';
        thanks.setAttribute('role', 'status');
        wrapper.appendChild(thanks);
    }

    // =========================================================================
    // Error & Clarification Rendering
    // =========================================================================

    /**
     * Render an error message in the chat.
     */
    function renderError(query, message) {
        const block = document.createElement('div');
        block.className = 'message-block error';
        block.setAttribute('role', 'alert');

        const queryEl = document.createElement('p');
        queryEl.className = 'user-query';
        queryEl.textContent = query;
        block.appendChild(queryEl);

        const errorEl = document.createElement('p');
        errorEl.className = 'error-message';
        errorEl.textContent = message;
        block.appendChild(errorEl);

        messagesArea.appendChild(block);
        scrollToBottom();
    }

    /**
     * Render a clarification prompt from the system.
     */
    function renderClarification(query, clarificationPrompt) {
        const block = document.createElement('div');
        block.className = 'message-block clarification';
        block.setAttribute('role', 'status');

        const queryEl = document.createElement('p');
        queryEl.className = 'user-query';
        queryEl.textContent = query;
        block.appendChild(queryEl);

        const clarEl = document.createElement('p');
        clarEl.className = 'clarification-message';
        clarEl.textContent = clarificationPrompt;
        block.appendChild(clarEl);

        messagesArea.appendChild(block);
        scrollToBottom();
    }

    // =========================================================================
    // Utility Functions
    // =========================================================================

    /**
     * Set loading state for the UI.
     */
    function setLoading(loading) {
        isLoading = loading;
        loadingIndicator.hidden = !loading;
        sendBtn.disabled = loading;
        queryInput.disabled = loading;
    }

    /**
     * Remove the welcome message on first query.
     */
    function clearWelcomeMessage() {
        const welcome = messagesArea.querySelector('.welcome-message');
        if (welcome) welcome.remove();
    }

    /**
     * Scroll messages area to the bottom.
     */
    function scrollToBottom() {
        messagesArea.scrollTop = messagesArea.scrollHeight;
    }

    /**
     * Escape HTML entities to prevent XSS.
     */
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

})();
