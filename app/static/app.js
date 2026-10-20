const KEY = 'hachiware.chat.v1';
const NOTICE_KEY = 'hachiware.notice.v1';
// app/messages.py와 같은 문구 (서버 응답 없는 경우용)
const MSG_RETRY = '*고개를 갸웃한다* 어… 잠깐 말이 안 나와… 다시 말해줄래?';
const MSG_RATE = '*숨을 고른다* 잠깐만… 너무 빨라서 따라가기 어려워…';

const $ = (id) => document.getElementById(id);
const log = $('log'), chips = $('chips'), input = $('input'), sendBtn = $('send');

let msgs = [];
let busy = false;
let dead = false; // 크레딧 소진
let errorText = null; // 저장 안 하는 오류 말풍선

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* 메모리로만 동작 */ } },
};
const save = () => store.set(KEY, JSON.stringify(msgs));

function load() {
  try {
    const v = JSON.parse(store.get(KEY));
    if (Array.isArray(v)) return v.filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string');
  } catch { /* 없거나 깨짐 */ }
  return [];
}

// 맨 앞 *...* 를 지문으로 분리. 닫는 * 가 아직 없으면 전부 지문(스트리밍 중)
function split(text, streaming) {
  const m = text.match(/^\s*\*([^*]*)\*\s*/);
  if (m) return [m[1], text.slice(m[0].length)];
  if (streaming && /^\s*\*[^*]*$/.test(text)) return [text.replace(/^\s*\*/, ''), ''];
  return ['', text];
}

// 지문 단어로 표정 고르기. 앞쪽 규칙 우선. 지문 없음 = 위기 응답 → 슬픔
const FACES = [
  ['joy', /반짝|살랑|웃는|웃으|웃어|웃음|미소|신나|폴짝|활짝/],  // '웃'만 쓰면 '갸웃'에 걸림
  ['sad', /처지|처진|처졌|눈물|훌쩍|울먹/],
  ['hesitate', /갸웃|머뭇|만지작|우물쭈물|망설/],
  ['excite', /쫑긋|동그랗|두근|설레/],
];
function face(act) {
  if (!act) return 'sad';
  const f = FACES.find(([, re]) => re.test(act));
  return f ? f[0] : 'base';
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function hwRow(text, { streaming = false, m = null, last = false } = {}) {
  const row = el('div', 'row hw');
  let mood = 'base', act = '', line = '';
  if (text) {
    [act, line] = split(text, streaming);
    if (line || !streaming) mood = face(act);  // 지문이 다 들어온 뒤에 표정 결정
  }
  const img = el('img', 'face');
  img.src = `/static/face/${mood}.webp`;
  img.alt = '';
  const b = el('div', 'bubble');
  b.append(text ? line : el('span', 'dots', '…'));
  row.append(img, el('div', 'act', act), b);
  if (last && m && m.trace_id) row.append(feedback(m));  // 👍👎는 마지막 응답에만
  row.dataset.mood = mood;
  return row;
}

function feedback(m) {
  const box = el('div', 'fb');
  for (const [val, tpl, label] of [[1, 'thumb-up', '좋아요'], [-1, 'thumb-down', '별로예요']]) {
    const b = el('button');
    b.type = 'button';
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-pressed', String(m.fb === val));
    b.append($(tpl).content.cloneNode(true));
    b.onclick = () => rate(m, val);
    box.append(b);
  }
  return box;
}

async function rate(m, val) {
  val = m.fb === val ? 0 : val;  // 같은 걸 다시 누르면 취소
  m.fb = val || undefined;
  save();
  render();
  try {
    await fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trace_id: m.trace_id, value: val }) });
  } catch { /* 표시만 유지 */ }
}

function render(streamText = null) {
  log.replaceChildren();
  msgs.forEach((m, i) => {
    if (m.role === 'user') {
      const row = el('div', 'row me');
      row.append(el('div', 'bubble', m.content));
      log.append(row);
    } else {
      log.append(hwRow(m.content, { m, last: i === msgs.length - 1 }));
    }
  });
  if (streamText !== null) log.append(hwRow(streamText, { streaming: true }));
  if (errorText) log.append(hwRow(errorText));
  const rows = log.querySelectorAll('.row.hw');
  if (rows.length) $('top-face').src = `/static/face/${rows[rows.length - 1].dataset.mood}.webp`;  // 상단 얼굴 = 최근 표정
  fit(log);
  $('scroller').scrollTop = $('scroller').scrollHeight;
  const off = busy || dead;
  input.disabled = off;
  sendBtn.disabled = off;
  chips.querySelectorAll('button').forEach((b) => (b.disabled = off));
  if (dead) input.placeholder = '지금은 얘기할 수 없어요';
}

// 여러 줄 말풍선은 최대 폭까지 늘어나 오른쪽이 빔 → 실제 줄 폭에 맞춰 줄임
// ponytail: 그릴 때마다 전체 말풍선을 잼. 대화가 아주 길어 느려지면 마지막 것만
function fit(root) {
  for (const b of root.querySelectorAll('.bubble')) {
    b.style.width = '';
    const r = document.createRange();
    r.selectNodeContents(b);
    const rects = [...r.getClientRects()];
    if (rects.length < 2) continue;
    const w = Math.max(...rects.map((x) => x.right)) - Math.min(...rects.map((x) => x.left));
    const cs = getComputedStyle(b);
    b.style.width = `${Math.ceil(w + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth))}px`;
  }
}
addEventListener('resize', () => fit(log));
document.fonts?.ready.then(() => fit(log));  // 웹폰트가 늦게 오면 폭이 바뀜

function setChips(list) {
  chips.replaceChildren();
  for (const s of list) {
    const b = el('button', null, s);
    b.type = 'button';
    b.onclick = () => send(s);
    chips.append(b);
  }
  render(busy ? '' : null);
}

async function suggest() {
  setChips([]);
  if (!msgs.length || msgs[msgs.length - 1].role !== 'assistant' || dead) return;
  try {
    const r = await fetch('/api/suggest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: payload() }) });
    if (!r.ok) return;
    const { suggestions } = await r.json();
    if (Array.isArray(suggestions) && !busy) setChips(suggestions);
  } catch { /* 칩 숨김 */ }
}

// 최근 80~160개만 전송. 80개 단위로 잘라 앞부분이 매 턴 바뀌지 않게(캐시 유지), 서버 상한 200 아래 유지
const WINDOW = 80;
const payload = () => {
  const start = msgs.length <= WINDOW * 2 ? 0 : Math.floor((msgs.length - WINDOW) / WINDOW) * WINDOW;
  return msgs.slice(start).map(({ role, content }) => ({ role, content }));
};

// SSE 파서: 이벤트 경계 \n\n, 청크가 중간에서 잘려도 버퍼에 보관
async function readSSE(res, onEvent) {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  const flush = (block) => {
    let event = 'message', data = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data += line.slice(5).trim();
    }
    if (data) onEvent(event, JSON.parse(data));
  };
  for (;;) {
    const { value, done } = await reader.read();
    buf += dec.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, '\n');
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      flush(buf.slice(0, i));
      buf = buf.slice(i + 2);
    }
    if (done) break;
  }
  if (buf.trim()) flush(buf);
}

function fail(text, userText, credit = false) {
  // 사용자 메시지는 입력창으로 복원
  if (msgs.length && msgs[msgs.length - 1].role === 'user') msgs.pop();
  save();
  errorText = text;
  input.value = userText;
  if (credit) dead = true;
}

async function send(text) {
  text = text.trim();
  if (!text || busy || dead) return;
  busy = true; // 연타 방지: 동기적으로 먼저 잠금
  errorText = null;
  input.value = '';
  setChips([]);
  msgs.push({ role: 'user', content: text });
  save();
  render('');

  let acc = '', traceId = null, failed = false;
  try {
    const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: payload() }) });
    if (!res.ok) {
      let message = res.status === 429 ? MSG_RATE : MSG_RETRY;
      // 429는 방화벽 응답이라 본문이 우리 형식이 아님 → 고정 문구 유지
      if (res.status !== 429) { try { message = (await res.json()).message || message; } catch { /* 본문 없음 */ } }
      fail(message, text);
      failed = true;
    } else {
      await readSSE(res, (ev, d) => {
        if (ev === 'delta') { acc += d.text; render(acc); }
        else if (ev === 'done') traceId = d.trace_id;
        else if (ev === 'error') {
          fail(d.message || MSG_RETRY, text, d.code === 'credit');
          failed = true;
        }
      });
    }
  } catch {
    if (!failed) { fail(MSG_RETRY, text); failed = true; }
  }
  if (!failed && traceId) {
    msgs.push({ role: 'assistant', content: acc.slice(0, 2000), trace_id: traceId });  // 서버 assistant 상한과 같게
    save();
  } else if (!failed) { // done 없이 스트림 종료
    fail(MSG_RETRY, text);
    failed = true;
  }
  busy = false;
  render();
  if (!failed) suggest();
  else if (!dead) input.focus();
}

$('form').onsubmit = (e) => { e.preventDefault(); send(input.value); };

$('mode').onclick = () => {
  const tone = $('tone').hidden;  // 지금 대화면 → 말투 변환으로
  $('tone').hidden = !tone;
  $('chat').hidden = tone;
  $('mode').textContent = tone ? '대화로' : '말투 변환';
};

// 말투 변환
const toneIn = $('tone-input'), toneOut = $('tone-out'), toneGo = $('tone-go');
toneIn.oninput = () => { $('tone-count').textContent = `${toneIn.value.length}/200`; };

function toneCard(title, text) {
  const c = document.createElement('div');
  c.className = 'card';
  const h = document.createElement('h2'); h.textContent = title;
  const p = document.createElement('p'); p.textContent = text;
  c.append(h, p);
  if (title !== '하치와레') {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = '복사';
    b.onclick = async () => {
      try { await navigator.clipboard.writeText(text); b.textContent = '복사했어요'; }
      catch { b.textContent = '복사 안 됨'; }
    };
    c.append(b);
  }
  return c;
}

$('tone-form').onsubmit = async (e) => {
  e.preventDefault();
  const text = toneIn.value.trim();
  if (!text || toneGo.disabled) return;
  toneGo.disabled = true;
  toneOut.replaceChildren(toneCard('하치와레', '음… 어떻게 바꿀까…'));
  let cards;
  try {
    const r = await fetch('/api/convert', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.refused) cards = [toneCard('하치와레', d.refused)];
    else if (r.ok) cards = [toneCard('얄밉게', d.intent), toneCard('더 얄밉게', d.twist)];
    else cards = [toneCard('하치와레', (r.status === 429 ? MSG_RATE : d.message || MSG_RETRY).replace(/^\*[^*]*\*\s*/, ''))];
  } catch {
    cards = [toneCard('하치와레', MSG_RETRY.replace(/^\*[^*]*\*\s*/, ''))];
  }
  toneOut.replaceChildren(...cards);
  toneGo.disabled = false;
};

async function init() {
  msgs = load();
  render();
  if (!msgs.length) {
    try {
      const r = await fetch('/api/intro');
      msgs = [{ role: 'assistant', content: (await r.json()).text }];
      save();
    } catch {
      errorText = MSG_RETRY;
    }
    render();
  }
  if (!store.get(NOTICE_KEY)) {
    const d = $('notice-dialog');
    $('notice-ok').onclick = () => { store.set(NOTICE_KEY, '1'); d.close(); };
    if (d.showModal) d.showModal();
  }
  suggest();
}
init();
