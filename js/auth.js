class AuthManager {
    constructor() {
        this.storageKey = 'tsg_user_session';
        this.apiBaseUrl = '/api'; // Замените на ваш API endpoint
    }

    validateEmail(email) {
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return re.test(email);
    }

    validatePassword(password) {
        return password.length >= 6;
    }

    validateName(name) {
        return name.trim().length >= 2;
    }

    validateFormData(formData) {
        const errors = {};

        if (!this.validateName(formData.name)) {
            errors.name = 'Введите корректное имя (минимум 2 символа)';
        }

        if (!this.validateEmail(formData.email)) {
            errors.email = 'Введите корректный email адрес';
        }

        if (!this.validatePassword(formData.password)) {
            errors.password = 'Пароль должен содержать минимум 6 символов';
        }

        return {
            isValid: Object.keys(errors).length === 0,
            errors
        };
    }

    async login(credentials) {
        try {
            // Имитация API запроса (замените на реальный запрос)
            const response = await this.mockLoginAPI(credentials);
            
            if (response.success) {
                this.saveSession(response.data);
                return { success: true, data: response.data };
            } else {
                return { success: false, error: response.error };
            }
        } catch (error) {
            console.error('Login error:', error);
            return { success: false, error: 'Ошибка соединения с сервером' };
        }
    }

    saveSession(userData) {
        const sessionData = {
            ...userData,
            loginTime: new Date().toISOString()
        };
        localStorage.setItem(this.storageKey, JSON.stringify(sessionData));
    }

    getSession() {
        const session = localStorage.getItem(this.storageKey);
        return session ? JSON.parse(session) : null;
    }

    logout() {
        localStorage.removeItem(this.storageKey);
        window.location.href = 'index.html';
    }

    isAuthenticated() {
        return this.getSession() !== null;
    }

    async mockLoginAPI(credentials) {
        // Имитация задержки сети
        await new Promise(resolve => setTimeout(resolve, 1000));

        // Пример проверки (в реальности это делает сервер)
        const mockUsers = [
            {
                name: 'Иван',
                email: 'ivan@test.ru',
                password: '123456',
                id: 1,
                apartment: '101',
                building: 'ЖК Солнечный'
            }
        ];

        const user = mockUsers.find(u => 
            u.email === credentials.email && 
            u.password === credentials.password
        );

        if (user) {
            return {
                success: true,
                data: {
                    id: user.id,
                    name: user.name,
                    email: user.email,
                    apartment: user.apartment,
                    building: user.building
                }
            };
        } else {
            return {
                success: false,
                error: 'Неверное имя пользователя или пароль'
            };
        }
    }
}

// Экспорт экземпляра
const authManager = new AuthManager();