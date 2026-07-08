document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const nameInput = document.getElementById('name');
    const emailInput = document.getElementById('email');
    const passwordInput = document.getElementById('password');
    const togglePasswordBtn = document.getElementById('togglePassword');
    const loginBtn = document.getElementById('loginBtn');
    const authError = document.getElementById('authError');
    const helpLink = document.getElementById('helpLink');
    const helpModal = document.getElementById('helpModal');
    const modalClose = document.getElementById('modalClose');
    const modalOverlay = document.querySelector('.modal-overlay');

    if (authManager.isAuthenticated()) {
        window.location.href = 'main.html';
    }

    togglePasswordBtn.addEventListener('click', () => {
        const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
        passwordInput.setAttribute('type', type);
        
        togglePasswordBtn.innerHTML = type === 'password' 
            ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                <circle cx="12" cy="12" r="3"></circle>
               </svg>`
            : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                <line x1="1" y1="1" x2="23" y2="23"></line>
               </svg>`;
    });

    [nameInput, emailInput, passwordInput].forEach(input => {
        input.addEventListener('input', () => {
            clearFieldError(input.id);
            hideAuthError();
        });
    });

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        hideAuthError();
        clearAllErrors();

        const formData = {
            name: nameInput.value.trim(),
            email: emailInput.value.trim(),
            password: passwordInput.value
        };

        const validation = authManager.validateFormData(formData);
        
        if (!validation.isValid) {
            showValidationErrors(validation.errors);
            return;
        }

        setLoading(true);

        try {
            const result = await authManager.login(formData);

            if (result.success) {
                window.location.href = 'main.html';
            } else {
                showAuthError(result.error);
            }
        } catch (error) {
            showAuthError('Произошла ошибка. Попробуйте позже.');
        } finally {
            setLoading(false);
        }
    });

    helpLink.addEventListener('click', (e) => {
        e.preventDefault();
        helpModal.classList.add('active');
        document.body.style.overflow = 'hidden';
    });

    function closeModal() {
        helpModal.classList.remove('active');
        document.body.style.overflow = '';
    }

    modalClose.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', closeModal);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && helpModal.classList.contains('active')) {
            closeModal();
        }
    });


    function showValidationErrors(errors) {
        Object.keys(errors).forEach(field => {
            showFieldError(field, errors[field]);
        });
    }

    function showFieldError(fieldId, message) {
        const input = document.getElementById(fieldId);
        const errorElement = document.getElementById(`${fieldId}Error`);
        
        input.classList.add('error');
        errorElement.textContent = message;
        errorElement.classList.add('show');
    }

    function clearFieldError(fieldId) {
        const input = document.getElementById(fieldId);
        const errorElement = document.getElementById(`${fieldId}Error`);
        
        input.classList.remove('error');
        errorElement.classList.remove('show');
    }

    function clearAllErrors() {
        ['name', 'email', 'password'].forEach(field => clearFieldError(field));
    }

    function showAuthError(message) {
        authError.querySelector('span').textContent = message;
        authError.style.display = 'flex';
    }

    function hideAuthError() {
        authError.style.display = 'none';
    }

    function setLoading(loading) {
        if (loading) {
            loginBtn.classList.add('loading');
            loginBtn.disabled = true;
        } else {
            loginBtn.classList.remove('loading');
            loginBtn.disabled = false;
        }
    }
});