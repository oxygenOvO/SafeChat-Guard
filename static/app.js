const form = document.querySelector('#chat-form');
const textarea = document.querySelector('#message');
const messages = document.querySelector('#messages');
const result = document.querySelector('#result');
const stats = document.querySelector('#stats');

function addMessage(text, role) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = text;
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

async function refreshStats() {
  const res = await fetch('/api/stats');
  stats.textContent = JSON.stringify(await res.json(), null, 2);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = textarea.value.trim();
  if (!message) return;
  addMessage(message, 'user');
  textarea.value = '';
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message}),
  });
  const data = await res.json();
  addMessage(data.reply, 'assistant');
  result.textContent = JSON.stringify(data, null, 2);
  refreshStats();
});

refreshStats();
