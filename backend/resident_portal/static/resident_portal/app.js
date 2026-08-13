(() => {
  const widget = document.querySelector('[data-ai-widget]');
  if (!widget) return;

  const panel = widget.querySelector('[data-ai-panel]');
  const form = widget.querySelector('[data-ai-form]');
  const textarea = form.querySelector('textarea');
  const log = widget.querySelector('[data-ai-log]');
  const result = widget.querySelector('[data-ai-result]');
  const analyzeButton = form.querySelector('button');
  const createButton = widget.querySelector('[data-ai-create]');
  const analyzeButtonText = analyzeButton.textContent;
  const createButtonText = createButton.textContent;
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  let lastMessage = '';
  let lastAnalysis = null;

  const addMessage = (role, text) => {
    const item = document.createElement('div');
    item.className = `ai-widget-message ${role}`;
    item.textContent = text;
    log.appendChild(item);
    log.scrollTop = log.scrollHeight;
    return item;
  };

  const postJson = async (url, payload) => {
    const response = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Ошибка запроса');
    return data;
  };

  const setLoading = (loading, mode = 'analyze') => {
    analyzeButton.disabled = loading;
    createButton.disabled = loading;
    analyzeButton.textContent = loading && mode === 'analyze'
      ? 'Разбираю...'
      : analyzeButtonText;
    createButton.textContent = loading && mode === 'create'
      ? 'Отправляю...'
      : createButtonText;
  };

  const fillResult = (analysis) => {
    widget.querySelector('[data-ai-title]').textContent = analysis.title;
    widget.querySelector('[data-ai-location]').textContent = analysis.location;
    widget.querySelector('[data-ai-category]').textContent = analysis.category_name;
    widget.querySelector('[data-ai-priority]').textContent = analysis.priority_label;
    widget.querySelector('[data-ai-summary]').textContent = analysis.summary;
    result.hidden = false;
  };

  widget.querySelector('[data-ai-toggle]').addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) textarea.focus();
  });

  widget.querySelector('[data-ai-close]').addEventListener('click', () => {
    panel.hidden = true;
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') panel.hidden = true;
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const message = textarea.value.trim();
    if (!message) return;

    lastMessage = message;
    lastAnalysis = null;
    result.hidden = true;
    addMessage('user', message);
    const pendingMessage = addMessage('assistant pending', 'Разбираю обращение...');
    setLoading(true, 'analyze');

    try {
      const data = await postJson(widget.dataset.analyzeUrl, {message});
      lastAnalysis = data.analysis;
      pendingMessage.className = 'ai-widget-message assistant';
      pendingMessage.textContent = lastAnalysis.resident_reply;
      fillResult(lastAnalysis);
    } catch (error) {
      pendingMessage.className = 'ai-widget-message assistant';
      pendingMessage.textContent = error.message;
    } finally {
      setLoading(false);
    }
  });

  createButton.addEventListener('click', async () => {
    if (!lastMessage || !lastAnalysis) return;

    setLoading(true, 'create');
    try {
      const data = await postJson(widget.dataset.createUrl, {
        message: lastMessage,
      });
      window.location.href = data.ticket_url;
    } catch (error) {
      addMessage('assistant', error.message);
    } finally {
      setLoading(false);
    }
  });
})();
