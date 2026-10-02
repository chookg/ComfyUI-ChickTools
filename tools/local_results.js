/* Append results without replacing existing media elements or changing playback state. */
(() => {
  const byId = id => document.getElementById(id);
  const messageCards = new Map();
  const mediaCards = new Map();
  let session = null;
  let revision = -1;
  let socket;
  let reconnectTimer;
  let stopped = false;
  let listening = false;

  function element(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  }

  function render(data) {
    if (data.session === session && data.revision < revision) return;
    session = data.session;
    revision = data.revision;
    const successes = data.media.filter(item => !item.error).length;
    byId('status').textContent = `已接收 ${data.received} 条消息 · ${successes} 个媒体已解码`;
    for (const item of data.messages) {
      if (messageCards.has(item.event_id)) continue;
      const card = element('article');
      card.append(element('time', item.received_at), element('pre', JSON.stringify({id: item.id, msg: item.msg}, null, 2)));
      messageCards.set(item.event_id, card);
      byId('messages').append(card);
      byId('messages-empty').hidden = true;
    }
    for (const item of data.media) {
      if (mediaCards.has(item.id)) continue;
      const card = element('article');
      card.dataset.mediaId = item.id;
      card.append(element('strong', item.source));
      if (item.error) {
        card.append(element('p', `解码失败：${item.error}`, 'error'));
      } else {
        let player;
        if (['mp4', 'webm'].includes(item.extension)) player = element('video');
        else if (['wav', 'mp3', 'ogg'].includes(item.extension)) player = element('audio');
        else player = element('img');
        if (player.tagName === 'IMG') player.alt = '解码后的图片';
        else {
          player.controls = true;
          player.preload = 'metadata';
          player.setAttribute('playsinline', '');
        }
        player.src = item.url;
        card.append(element('p', `${item.extension.toUpperCase()} · ${item.size.toLocaleString()} bytes`, 'muted'), player);
        const links = element('p');
        const decoded = element('a', '下载解码文件');
        decoded.href = item.url;
        decoded.download = `${item.source}.${item.extension}`;
        const carrier = element('a', '查看原始载体 PNG');
        carrier.href = item.carrier_url;
        carrier.target = '_blank';
        carrier.rel = 'noopener';
        links.append(decoded, element('span', ' · '), carrier);
        card.append(links);
      }
      mediaCards.set(item.id, card);
      byId('media').append(card);
      byId('media-empty').hidden = true;
    }
  }

  function disconnect() {
    clearTimeout(reconnectTimer);
    const previous = socket;
    socket = null;
    if (previous) previous.close();
  }

  function connect() {
    if (stopped || !listening || socket) return;
    byId('connection').textContent = '正在连接…';
    const current = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    socket = current;
    current.onopen = () => {
      if (socket === current) byId('connection').textContent = '正在监听，新结果会自动显示';
    };
    current.onmessage = event => {
      if (socket !== current) return;
      try { render(JSON.parse(event.data)); }
      catch { byId('connection').textContent = '结果格式异常，请停止后重新开启监听'; }
    };
    current.onclose = () => {
      if (socket !== current) return;
      socket = null;
      if (stopped || !listening) return;
      byId('connection').textContent = '连接中断，正在重连；已加载的视频可继续播放';
      reconnectTimer = setTimeout(connect, 2000);
    };
  }

  byId('url').textContent = `${location.origin}/callback`;
  byId('listen').addEventListener('click', () => {
    listening = !listening;
    byId('listen').textContent = listening ? '停止监听' : '开启监听';
    byId('listen').setAttribute('aria-pressed', String(listening));
    if (listening) connect();
    else {
      disconnect();
      byId('connection').textContent = '已停止监听，已加载的内容会保留';
    }
  });
  window.addEventListener('pagehide', () => {
    stopped = true;
    disconnect();
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) { stopped = false; connect(); }
  });
  // Start only on request. The WebSocket sends both the first snapshot and updates.
})();
