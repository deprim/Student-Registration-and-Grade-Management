/* Progressive enhancement only: every workflow also works with standard HTML forms. */
document.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]), textarea').forEach((field) => {
    field.classList.add('form-control');
});
document.querySelectorAll('select').forEach((field) => field.classList.add('form-select'));
document.querySelectorAll('.side-nav a.active').forEach((link) => link.setAttribute('aria-current', 'page'));
document.querySelectorAll('[data-print]').forEach((button) => {
    button.addEventListener('click', () => window.print());
});

const autocomplete = {
    username: 'username', email: 'email', first_name: 'given-name', last_name: 'family-name',
    password: 'current-password', old_password: 'current-password',
    password1: 'new-password', password2: 'new-password',
    new_password1: 'new-password', new_password2: 'new-password',
};
document.querySelectorAll('input:not([type="hidden"]), textarea, select').forEach((field) => {
    if (!field.hasAttribute('autocomplete')) field.autocomplete = autocomplete[field.name] || 'off';
    if (field.type === 'email') {
        field.inputMode = 'email';
        field.spellcheck = false;
        field.autocapitalize = 'none';
    }
    if (field.type === 'number') field.inputMode = 'numeric';
    if (field.name === 'q') field.type = 'search';
    if (field.name.endsWith('-comment')) field.placeholder = 'Add a comment…';
    if (field.hasAttribute('autofocus') && window.matchMedia('(max-width: 767px)').matches) {
        field.removeAttribute('autofocus');
        window.addEventListener('load', () => {
            if (document.activeElement === field) field.blur();
        }, {once: true});
    }
});

/* Django renders server-side errors; keep descriptions linked to their fields. */
document.querySelectorAll('.field-group.has-error').forEach((group) => {
    const field = group.querySelector('input, textarea, select');
    const error = group.querySelector('[id$="_error"]');
    if (field && error) {
        field.setAttribute('aria-invalid', 'true');
        const descriptions = new Set((field.getAttribute('aria-describedby') || '').split(' ').filter(Boolean));
        descriptions.add(error.id);
        field.setAttribute('aria-describedby', [...descriptions].join(' '));
    }
});
const firstError = document.querySelector('[aria-invalid="true"]');
if (firstError) firstError.focus();
else {
    const formError = document.querySelector('form .alert-danger');
    if (formError) {
        formError.tabIndex = -1;
        formError.focus();
    }
}

/* Only scrollable data regions enter the tab order. */
const tables = [...document.querySelectorAll('.table-responsive')];
const tableHints = tables.map((region) => {
    const hint = document.createElement('p');
    hint.className = 'table-scroll-hint';
    hint.textContent = 'Scroll to see all columns →';
    hint.hidden = true;
    region.before(hint);
    return hint;
});
function updateTableFocus() {
    const overflowing = tables.map((region) => region.scrollWidth > region.clientWidth);
    tables.forEach((region, index) => {
        tableHints[index].hidden = !overflowing[index];
        if (overflowing[index]) {
            region.tabIndex = 0;
            region.setAttribute('role', 'region');
            const heading = region.closest('section')?.querySelector('h2') || document.querySelector('h1');
            region.setAttribute('aria-label', `${heading?.textContent.trim() || 'Records'} — scrollable table`);
        } else {
            region.removeAttribute('tabindex');
            region.removeAttribute('role');
            region.removeAttribute('aria-label');
        }
    });
}
if (tables.length) {
    updateTableFocus();
    window.addEventListener('resize', updateTableFocus);
    document.fonts.ready.then(updateTableFocus);
}

const gradebook = document.querySelector('#gradebook-form');
let gradesChanged = false;
if (gradebook) {
    const status = document.createElement('span');
    status.setAttribute('role', 'status');
    const footerText = gradebook.querySelector('.gradebook-footer > span');
    if (footerText) {
        status.textContent = footerText.textContent;
        footerText.replaceWith(status);
    }
    gradebook.addEventListener('input', () => {
        gradesChanged = true;
        status.textContent = 'Unsaved changes. Save grades to update student records.';
    });
    gradebook.addEventListener('submit', () => { gradesChanged = false; });
    window.addEventListener('beforeunload', (event) => {
        if (gradesChanged) {
            event.preventDefault();
            event.returnValue = '';
        }
    });
}

/* Prevent repeated submissions after native validation passes. Preserve button values. */
document.querySelectorAll('form[method="post"]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        if (form.dataset.submitting === 'true') {
            event.preventDefault();
            return;
        }
        form.dataset.submitting = 'true';
        form.setAttribute('aria-busy', 'true');
        const button = event.submitter;
        if (button && !button.name) {
            button.dataset.originalLabel = button.textContent;
            button.textContent = 'Please wait…';
            button.disabled = true;
        }
    });
});
window.addEventListener('pageshow', () => {
    document.querySelectorAll('form[data-submitting]').forEach((form) => {
        delete form.dataset.submitting;
        form.removeAttribute('aria-busy');
        form.querySelectorAll('[data-original-label]').forEach((button) => {
            button.textContent = button.dataset.originalLabel;
            button.disabled = false;
            delete button.dataset.originalLabel;
        });
    });
});
