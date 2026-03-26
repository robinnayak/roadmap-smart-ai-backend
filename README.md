# Roadmap Smart Planner API

## Overview

The Roadmap Smart Planner API is a scalable SaaS platform that leverages AI (Claude/Ollama) to generate personalized 20,000-word life roadmaps with daily action plans. It bridges the gap between expensive personal coaching and generic self-help content by creating deeply customized transformation plans in minutes, then tracking user progress through daily check-ins, analytics, and gamified accountability features.

The platform assists users in achieving goals across career, financial, health, and personal development domains, focusing on building discipline and motivation through structured, AI-generated hierarchies: Goals → Milestones → SubGoals → Daily Tasks.

## Configuration Guide

For environment switching, production configuration, and service-switching guidance, see:

- [`project_docs/apis/production/ENVIRONMENT_AND_SERVICE_SWITCHING_GUIDE.md`](../project_docs/apis/production/ENVIRONMENT_AND_SERVICE_SWITCHING_GUIDE.md)

This guide covers:
- LLM provider and model switching
- database switching between SQLite and PostgreSQL
- storage switching between local files and Cloudflare R2
- Celery eager versus Redis-backed async execution
- frontend URL and auth-related environment configuration

### Key Features
- **AI-Powered Roadmap Generation**: Uses Ollama local models for precise, requirement-specific AI/ML engine.
- **Hierarchical Goal Management**: Goals broken into milestones (monthly), subgoals (weekly), and tasks (daily).
- **Daily Routine Tracking**: Gamified daily task lists with habit tracking and discipline streaks.
- **User Personalization**: Profiles, personal details, and context-aware AI generation.
- **Progress Analytics**: Real-time tracking, completion rates, and motivational insights.
- **Scalable Architecture**: Django REST Framework with JWT authentication, suitable for production deployment.

## Tech Stack
- **Backend**: Django 6.0, Django REST Framework 3.16
- **Database**: SQLite (development), PostgreSQL/MySQL (production)
- **Authentication**: JWT (djangorestframework-simplejwt)
- **AI Integration**: Ollama for local AI models
- **Other**: Django CORS headers, Python Decouple for config

## Setup

### Prerequisites
- Python 3.8+
- Ollama installed and running locally
- Git

### Local Development Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd roadmap-smart-planner-backend
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   python -m pip install -r roadmap/requirements.txt
   python -c "import reportlab,sys; print('reportlab', reportlab.__version__, 'from', sys.executable)"
   ```

4. **Environment variables**:
   Create a `.env` file in the project root:
   ```
   DJANGO_SECRET_KEY=your-secret-key-here
   DEBUG=True
   ALLOWED_HOSTS=localhost,127.0.0.1
   CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
   ACCESS_TOKEN_LIFETIME_MINUTES=60
   REFRESH_TOKEN_LIFETIME_DAYS=7
   ```

5. **Database setup**:
   ```bash
   python manage.py migrate
   ```

6. **Create superuser** (optional):
   ```bash
   python manage.py createsuperuser
   ```

7. **Run the server**:
   ```bash
   python roadmap/manage.py runserver
   ```
   The API will be available at `http://localhost:8000/`

8. **Interpreter-safe startup scripts** (recommended):
   ```bash
   # Windows
   ./start_backend.ps1

   # Linux/macOS
   ./start_backend.sh
   ```

### Production Deployment
- Use a production-grade database (PostgreSQL/MySQL)
- Set `DEBUG=False`
- Configure ALLOWED_HOSTS and CORS settings
- Use a WSGI server like Gunicorn
- Set up environment variables securely
- Enable HTTPS

## Authentication

The API uses JWT (JSON Web Tokens) for authentication. Include the token in the `Authorization` header as `Bearer <token>`.

Launch auth posture:
- JWT under `/auth/` is the only supported application auth contract.
- `/api-auth/` is a debug-only DRF browsable-API/session tool and is not part of the product surface.
- Notification settings endpoints store preference flags only; they do not imply a general push/email delivery subsystem.

### Obtaining Tokens
- Register a new user via `POST /auth/register/`
- Login via `POST /auth/login/` to receive access and refresh tokens
- Use the access token for authenticated requests
- Refresh tokens via `POST /auth/token/refresh/` when expired

### Token Expiration
- Access tokens: 1 hour (configurable)
- Refresh tokens: 7 days (configurable)

## API Endpoints

### Base
- `GET /` - Welcome message and API info

### Authentication

#### User Registration
- **Endpoint**: `POST /auth/register/`
- **Description**: Register a new user account
- **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "username": "optional_username",
    "password": "securepassword",
    "password2": "securepassword"
  }
  ```
- **Response (201)**:
  ```json
  {
    "tokens": {
      "access": "eyJ0eXAi...",
      "refresh": "eyJ0eXAi..."
    },
    "user": {
      "id": 1,
      "email": "user@example.com",
      "username": "user",
      "is_active": true,
      "date_joined": "2024-01-01T00:00:00Z",
      "last_login": null
    }
  }
  ```
- **Status Codes**: 201 (Created), 400 (Validation Error)

#### User Login
- **Endpoint**: `POST /auth/login/`
- **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "password": "securepassword"
  }
  ```
- **Response (200)**:
  ```json
  {
    "message": "Login successful",
    "tokens": {
      "access": "eyJ0eXAi...",
      "refresh": "eyJ0eXAi..."
    },
    "user": {...}
  }
  ```

#### User Logout
- **Endpoint**: `POST /auth/logout/`
- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
  ```json
  {
    "refresh_token": "eyJ0eXAi..."
  }
  ```

#### Token Refresh
- **Endpoint**: `POST /auth/token/refresh/`
- **Request Body**:
  ```json
  {
    "refresh": "eyJ0eXAi..."
  }
  ```

#### User Profile
- **Endpoint**: `GET /auth/profile/`, `PUT /auth/profile/`
- **Headers**: `Authorization: Bearer <token>`
- **Response**:
  ```json
  {
    "id": 1,
    "username": "user",
    "email": "user@example.com",
    "bio": "About me",
    "avatar": null,
    "timezone": "UTC",
    "subscription_tier": "free",
    "total_points": 0,
    "current_level": 1,
    "preferred_language": "en",
    "theme": "light"
  }
  ```

#### Personal Details
- **Endpoint**: `GET /auth/personal-details/`, `POST /auth/personal-details/`, `PUT /auth/personal-details/`, `DELETE /auth/personal-details/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body (POST/PUT)**:
  ```json
  {
    "date_of_birth": "1990-01-01",
    "current_situation": "Detailed description of current life situation",
    "roadmap_start_date": "2024-01-01"
  }
  ```

#### Notification Settings
- **Endpoint**: `GET /auth/notification/`, `PUT /auth/notification/`
- **Headers**: `Authorization: Bearer <token>`

#### User Info
- **Endpoint**: `GET /auth/user/`
- **Headers**: `Authorization: Bearer <token>`

#### Deactivate Account
- **Endpoint**: `POST /auth/user-deactivate/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body**:
  ```json
  {
    "deactivate": true
  }
  ```

### AI Services

#### AI Health Check
- **Endpoint**: `GET /ai/health-check/`
- **Description**: Check if AI service (Ollama) is running
- **Response (200)**:
  ```json
  {
    "status": "AI service is healthy",
    "service": "ollama",
    "host": "localhost:11434",
    "model": "gpt-oss:120b-cloud"
  }
  ```

#### Process Current Situation
- **Endpoint**: `POST /ai/process-text-data-current-situation/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body**:
  ```json
  {
    "raw_data": "Current situation description",
    "user_age": 30
  }
  ```
- **Response (200)**: Processed situation data with job ID

#### Goal Attribute Extractor
- **Endpoint**: `GET /ai/goal-attribute-extractor/`, `POST /ai/goal-attribute-extractor/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body (POST)**:
  ```json
  {
    "user_input": "I want to become a software engineer"
  }
  ```

#### Generate Milestones
- **Endpoint**: `GET /ai/generate-milestones/{goal_id}/`, `POST /ai/generate-milestones/{goal_id}/`
- **Headers**: `Authorization: Bearer <token>`
- **Response (200)**: Generated milestones for the goal

### Goal Management

#### Current Situation Goal
- **Endpoint**: `GET /goal/current-situation/`, `PUT /goal/current-situation/`, `DELETE /goal/current-situation/`
- **Headers**: `Authorization: Bearer <token>`

#### Goals
- **Endpoint**: `GET /goal/`, `POST /goal/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body (POST)**:
  ```json
  {
    "title": "Learn Python",
    "description": "Master Python programming",
    "why_it_matters": "Career advancement",
    "primary_category": "career",
    "impact_dimensions": {"skill": 8, "income": 7},
    "priority": "high",
    "target_date": "2024-12-31",
    "goal_attributes_input": "I need to learn Python for data science"
  }
  ```

#### Create Goal with Hierarchy
- **Endpoint**: `POST /goal/create-with-hierarchy/`
- **Headers**: `Authorization: Bearer <token>`
- **Description**: Creates goal and generates full AI hierarchy (milestones, subgoals, tasks)

#### Goal Detail
- **Endpoint**: `GET /goal/goals/{goal_id}/`, `PUT /goal/goals/{goal_id}/`, `DELETE /goal/goals/{goal_id}/`
- **Headers**: `Authorization: Bearer <token>`

#### Goal Hierarchy
- **Endpoint**: `GET /goal/goals/{goal_id}/hierarchy/`
- **Headers**: `Authorization: Bearer <token>`
- **Response**: Goal with milestones and subgoals (no tasks)

### Routine Management

#### Today's Task List
- **Endpoint**: `GET /routines/today/`
- **Headers**: `Authorization: Bearer <token>`
- **Response**: Today's generated task list

#### Generate Task List
- **Endpoint**: `POST /routines/generate/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body**:
  ```json
  {
    "date": "2024-01-15"
  }
  ```

#### Complete Task
- **Endpoint**: `POST /routines/tasks/{task_id}/complete/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body**:
  ```json
  {
    "notes": "Completed successfully",
    "actual_minutes": 45
  }
  ```

#### Skip Task
- **Endpoint**: `POST /routines/tasks/{task_id}/skip/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body**:
  ```json
  {
    "reason": "Not enough time today"
  }
  ```

#### Week Overview
- **Endpoint**: `GET /routines/week/`
- **Headers**: `Authorization: Bearer <token>`
- **Response**: Task completion summary for the current week

#### Discipline Streak
- **Endpoint**: `GET /routines/streak/`
- **Headers**: `Authorization: Bearer <token>`

#### Habits
- **Endpoint**: `GET /routines/habits/`, `POST /routines/habits/`
- **Headers**: `Authorization: Bearer <token>`
- **Request Body (POST)**:
  ```json
  {
    "name": "Morning Exercise",
    "description": "30 minutes of cardio",
    "frequency": "daily",
    "estimated_minutes": 30,
    "priority": "high"
  }
  ```

#### Habit Detail
- **Endpoint**: `GET /routines/habits/{habit_id}/`, `PUT /routines/habits/{habit_id}/`, `DELETE /routines/habits/{habit_id}/`
- **Headers**: `Authorization: Bearer <token>`

## Usage Examples

### Python (requests library)
```python
import requests

# Login
response = requests.post('http://localhost:8000/auth/login/', json={
    'email': 'user@example.com',
    'password': 'password'
})
token = response.json()['tokens']['access']

# Create a goal
headers = {'Authorization': f'Bearer {token}'}
response = requests.post('http://localhost:8000/goal/', json={
    'title': 'Learn Django',
    'description': 'Build web apps with Django',
    'primary_category': 'career',
    'target_date': '2024-06-01'
}, headers=headers)

print(response.json())
```

### cURL
```bash
# Register
curl -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass","password2":"pass"}'

# Login
TOKEN=$(curl -X POST http://localhost:8000/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass"}' | jq -r '.tokens.access')

# Get goals
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/goal/
```

## Error Handling

The API uses consistent error response formats:

```json
{
  "error": "Error message",
  "code": "error_code",
  "details": {...},  // Optional validation details
  "status": 400
}
```

### Common Error Codes
- `invalid_data`: Validation failed
- `token_not_valid`: JWT expired or invalid
- `not_found`: Resource not found
- `permission_denied`: Access denied
- `throttled`: Rate limit exceeded

### HTTP Status Codes
- `200`: Success
- `201`: Created
- `400`: Bad Request
- `401`: Unauthorized
- `403`: Forbidden
- `404`: Not Found
- `429`: Too Many Requests
- `500`: Internal Server Error

## Troubleshooting

### AI Service Issues
- Ensure Ollama is running: `ollama serve`
- Check model availability: `ollama list`
- Verify model name in health check response

### Database Issues
- Run migrations: `python manage.py migrate`
- Check database file permissions

### Authentication Issues
- Verify token format: `Bearer <token>`
- Check token expiration
- Ensure user is active

### Performance Issues
- Use pagination for large lists
- Implement caching for frequent queries
- Monitor database query performance

## Bug Tracking and Reporting

### Reporting Bugs
When encountering issues, follow these steps to report bugs effectively:

1. **Gather Information**:
   - Django version and Python version
   - Operating system and environment (dev/prod)
   - Steps to reproduce the issue
   - Expected vs. actual behavior
   - Error messages and stack traces
   - Relevant log entries

2. **Check Existing Issues**:
   - Search the issue tracker for similar problems
   - Review closed issues for known fixes

3. **Create a Bug Report**:
   - Use a clear, descriptive title
   - Provide detailed steps to reproduce
   - Include error logs and screenshots if applicable
   - Specify the environment where the issue occurs

4. **Debugging Tips**:
   - Enable DEBUG=True in development
   - Check Django logs in `roadmap/logs/`
   - Use Django Debug Toolbar for detailed request info
   - Test with minimal data to isolate issues

### Common Issue Categories
- **Authentication**: Token expiration, permission errors
- **AI Services**: Ollama connectivity, model loading
- **Database**: Migration issues, data integrity
- **API**: Request validation, serialization errors
- **Performance**: Slow queries, memory usage

## Coding Standards and Best Practices

### Code Quality Guidelines
1. **Remove Debug Code**: Eliminate all `print()` statements before production deployment
2. **Error Handling**: Use proper exception handling with logging
3. **Validation**: Implement comprehensive input validation
4. **Security**: Follow Django security best practices
5. **Performance**: Optimize database queries, use select_related/prefetch_related
6. **Documentation**: Document complex logic and API changes

### Development Workflow
1. **Branching**: Use feature branches for development
2. **Commits**: Write clear, descriptive commit messages
3. **Code Review**: All changes require review before merging
4. **Testing**: Write tests for new features and bug fixes
5. **Linting**: Use tools like flake8, black for code formatting

### Preventing Logical Errors
- **Duplicate Code**: Refactor duplicate classes and functions
- **Commented Code**: Remove unused commented code
- **Magic Numbers**: Use constants for configurable values
- **Hardcoded Values**: Use environment variables for configuration
- **Race Conditions**: Implement proper locking for concurrent operations

## Production Setup and Deployment

### Prerequisites
- **Server**: Ubuntu 20.04+ or similar Linux distribution
- **Python**: 3.8 or higher
- **Database**: PostgreSQL 12+ or MySQL 8+
- **Web Server**: Nginx
- **WSGI Server**: Gunicorn
- **AI Service**: Ollama server accessible
- **SSL Certificate**: For HTTPS (Let's Encrypt recommended)

### Step-by-Step Production Setup

1. **Server Preparation**:
   ```bash
   # Update system
   sudo apt update && sudo apt upgrade -y

   # Install required packages
   sudo apt install python3 python3-pip postgresql postgresql-contrib nginx curl
   ```

2. **Database Setup**:
   ```bash
   # Create database and user
   sudo -u postgres psql
   CREATE DATABASE roadmap_db;
   CREATE USER roadmap_user WITH PASSWORD 'secure_password';
   GRANT ALL PRIVILEGES ON DATABASE roadmap_db TO roadmap_user;
   \q
   ```

3. **Application Deployment**:
   ```bash
   # Clone repository
   git clone <repository-url>
   cd roadmap-smart-planner-backend

   # Create virtual environment
   python3 -m venv venv
   source venv/bin/activate

   # Install dependencies
   pip install -r requirements.txt
   pip install gunicorn psycopg2-binary
   ```

4. **Environment Configuration**:
   Create `.env` file:
   ```
   DJANGO_SECRET_KEY=your-very-secure-secret-key-here
   DEBUG=False
   ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
   CORS_ALLOWED_ORIGINS=https://yourfrontend.com
   DATABASE_URL=postgresql://roadmap_user:secure_password@localhost:5432/roadmap_db
   ACCESS_TOKEN_LIFETIME_MINUTES=60
   REFRESH_TOKEN_LIFETIME_DAYS=7
   OLLAMA_HOST=http://localhost:11434
   ```

5. **Database Migration**:
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

6. **Gunicorn Configuration**:
   Create `gunicorn.conf.py`:
   ```python
   bind = "127.0.0.1:8000"
   workers = 3
   user = "www-data"
   group = "www-data"
   tmp_upload_dir = None
   ```

7. **Nginx Configuration**:
   Create `/etc/nginx/sites-available/roadmap`:
   ```
   server {
       listen 80;
       server_name yourdomain.com www.yourdomain.com;

       location = /favicon.ico { access_log off; log_not_found off; }

       location / {
           include proxy_params;
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       location /static/ {
           alias /path/to/your/project/static/;
       }
   }
   ```

8. **Systemd Service**:
   Create `/etc/systemd/system/gunicorn.service`:
   ```
   [Unit]
   Description=Gunicorn daemon for Roadmap Planner
   After=network.target

   [Service]
   User=www-data
   Group=www-data
   WorkingDirectory=/path/to/your/project
   Environment="PATH=/path/to/your/project/venv/bin"
   ExecStart=/path/to/your/project/venv/bin/gunicorn roadmap.wsgi:application
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

9. **SSL Setup** (using Certbot):
   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
   ```

10. **Start Services**:
    ```bash
    sudo systemctl enable gunicorn
    sudo systemctl start gunicorn
    sudo systemctl enable nginx
    sudo systemctl restart nginx
    ```

### Monitoring and Maintenance
- **Logs**: Monitor `/var/log/nginx/` and application logs
- **Backups**: Regular database backups using pg_dump
- **Updates**: Test updates in staging environment first
- **Security**: Regular security updates and dependency checks

## Testing Protocols

### Testing Strategy
1. **Unit Tests**: Test individual functions and methods
2. **Integration Tests**: Test API endpoints and database interactions
3. **End-to-End Tests**: Test complete user workflows
4. **Performance Tests**: Load testing for production readiness

### Running Tests
```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test authentication
python manage.py test goal
python manage.py test ai
python manage.py test routine

# Run with coverage
pip install coverage
coverage run manage.py test
coverage report
```

## Backend Environment Contracts

- Logging is console-only in the active launch configuration unless explicit file handlers are added in [`roadmap/roadmap/settings.py`](./roadmap/roadmap/settings.py).
- The checked-in `roadmap/logs/` files are repository artifacts, not the active logging subsystem.
- Production rendering uses the shared JSON contract renderer only.
- The DRF browsable API renderer is enabled only when `DEBUG=True`.

### API Testing with cURL
```bash
# Health check
curl -X GET http://localhost:8000/ai/health-check/

# Register user
curl -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass","password2":"testpass"}'

# Test authentication flow
TOKEN=$(curl -X POST http://localhost:8000/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass"}' | jq -r '.tokens.access')

# Test protected endpoint
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/goal/
```

### Load Testing
Use tools like Apache Bench or Locust for performance testing:
```bash
# Simple load test
ab -n 1000 -c 10 http://localhost:8000/

# With authentication
ab -n 100 -c 5 -H "Authorization: Bearer $TOKEN" http://localhost:8000/goal/
```

### Continuous Integration
- Set up CI/CD pipeline with GitHub Actions
- Run tests on every push
- Deploy to staging on successful tests
- Manual approval for production deployment

## User Workflow Analysis

### Current User Journey
The application follows a logical, progressive user workflow designed to build comprehensive life transformation plans:

1. **Onboarding & Assessment**
   - User registration with profile creation
   - Personal details collection (age, current situation)
   - AI-powered current situation analysis

2. **Goal Setting & Planning**
   - Goal creation with AI attribute extraction
   - Automatic hierarchy generation (milestones → subgoals → tasks)
   - Flexible goal categorization (career, financial, health, personal)

3. **Daily Execution & Tracking**
   - AI-generated daily task lists from active goals
   - Task completion with progress tracking
   - Habit formation with streak counters
   - Real-time analytics and motivation

4. **Progress Monitoring**
   - Goal progress visualization
   - Weekly overview and reporting
   - Achievement tracking and gamification

### Workflow Logic Validation
✅ **Strengths**:
- Progressive complexity: Starts simple, builds depth
- AI integration reduces manual planning effort
- Daily habits reinforce long-term goals
- Comprehensive tracking prevents goal abandonment

✅ **User Experience Flow**:
- Intuitive progression from assessment to execution
- Clear feedback loops with progress indicators
- Flexible goal management (create, modify, track)
- Motivation through streaks and achievements

### Potential Workflow Improvements
- **Onboarding Enhancement**: Add goal discovery quiz before AI analysis
- **Progress Milestones**: Celebrate intermediate achievements
- **Adaptive Planning**: AI suggestions based on completion patterns
- **Social Accountability**: Optional goal sharing features

## Future Features Roadmap

### Phase 1: Enhanced Personalization (Q1 2025)
- **AI Coach Conversations**: Chat interface for personalized advice and motivation
- **Smart Reminders**: Intelligent notification system based on user patterns
- **Goal Templates**: Pre-built goal frameworks for common objectives
- **Progress Predictions**: AI forecasting of goal completion timelines

### Phase 2: Social & Community Features (Q2 2025)
- **Goal Sharing**: Private sharing with accountability partners
- **Community Challenges**: Group goal-setting and competitions
- **Mentorship Matching**: Connect users with similar goals
- **Success Stories**: User-generated content and testimonials

### Phase 3: Advanced Analytics & Insights (Q3 2025)
- **Life Pattern Analysis**: Identify habits and routines affecting goals
- **Predictive Insights**: AI recommendations based on user data
- **Custom Dashboards**: Personalized analytics views
- **Export Capabilities**: Data export for external analysis

### Phase 4: Integration & Expansion (Q4 2025)
- **Calendar Integration**: Sync with Google Calendar, Outlook
- **Wearable Integration**: Connect with fitness trackers, smart devices
- **Mobile App**: Native iOS/Android applications
- **API Expansions**: Third-party integrations (fitness apps, learning platforms)

### Phase 5: Enterprise & Advanced Features (2026)
- **Team Goal Management**: Organizational goal setting and tracking
- **Advanced Reporting**: Custom reports and analytics
- **White-label Solutions**: Custom branding for organizations
- **API Marketplace**: Third-party integrations and plugins

### Technical Enhancements
- **Real-time Collaboration**: Live goal editing and progress sharing
- **Offline Mode**: Core functionality without internet connection
- **Voice Commands**: Integration with voice assistants
- **AR/VR Elements**: Immersive goal visualization experiences

### Monetization Features
- **Premium Tiers**: Advanced AI features, unlimited goals
- **Corporate Plans**: Team management and reporting
- **Consultation Booking**: Direct connection with life coaches
- **Custom AI Models**: Personalized AI training on user data

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

This project is licensed under the MIT License.

**Licensed By**: ONEDAYGOAL  
**Author**: Robin Nayak

