'use strict';
document.getElementById('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.getElementById('login-submit');
  const error = document.getElementById('login-error');
  button.disabled = true;
  error.textContent = '';
  try {
    const response = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:document.getElementById('username').value, password:document.getElementById('password').value})});
    const data = await response.json();
    if (response.ok) location.assign('/');
    else error.textContent = data.error || 'Accesso non riuscito.';
  } catch (_) { error.textContent = 'Connessione non disponibile. Riprova.'; }
  finally { button.disabled = false; }
});
