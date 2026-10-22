# Reviewed source file manifest

These 133 project files form the reviewed Phase 1 source set. Local environments,
secrets, databases, private uploads, generated assets and review evidence are excluded.

- .env.example
- .gitattributes
- .github/workflows/ci.yml
- .gitignore
- .python-version
- IMPLEMENTATION_STATUS.md
- README.md
- academics/__init__.py
- academics/admin.py
- academics/apps.py
- academics/migrations/0001_initial.py
- academics/migrations/0002_initial.py
- academics/migrations/__init__.py
- academics/models.py
- accounts/__init__.py
- accounts/admin.py
- accounts/apps.py
- accounts/forms.py
- accounts/management/__init__.py
- accounts/management/commands/__init__.py
- accounts/management/commands/seed_demo.py
- accounts/management/commands/sync_roles.py
- accounts/migrations/0001_initial.py
- accounts/migrations/0002_user_user_email_not_blank.py
- accounts/migrations/__init__.py
- accounts/models.py
- accounts/roles.py
- accounts/urls.py
- accounts/views.py
- audit/__init__.py
- audit/admin.py
- audit/apps.py
- audit/migrations/0001_initial.py
- audit/migrations/__init__.py
- audit/models.py
- audit/services.py
- audit/signals.py
- build.sh
- config/__init__.py
- config/asgi.py
- config/settings/__init__.py
- config/settings/base.py
- config/settings/development.py
- config/settings/production.py
- config/settings/test.py
- config/urls.py
- config/wsgi.py
- core/__init__.py
- core/admin.py
- core/apps.py
- core/context_processors.py
- core/forms.py
- core/middleware.py
- core/migrations/0001_initial.py
- core/migrations/__init__.py
- core/models.py
- core/modules.py
- core/uploads.py
- core/urls.py
- core/views.py
- docs/ARCHITECTURE.md
- docs/CI.md
- docs/DATABASE.md
- docs/FILE_MANIFEST.md
- docs/PERMISSIONS.md
- docs/REPOSITORY_REVIEW.md
- docs/SECURITY.md
- docs/VERIFICATION.md
- manage.py
- people/__init__.py
- people/admin.py
- people/apps.py
- people/migrations/0001_initial.py
- people/migrations/__init__.py
- people/models.py
- people/selectors.py
- people/urls.py
- people/views.py
- pyproject.toml
- render.yaml
- requirements-browser.txt
- requirements-dev.txt
- requirements.txt
- scripts/browser_smoke.py
- scripts/configure_ci_database.py
- scripts/local_database.py
- scripts/repository_check.py
- static/css/schoolos.css
- static/img/mark.svg
- static/js/dashboard.js
- static/js/schoolos.js
- static/vendor/README.md
- static/vendor/bootstrap.LICENSE
- static/vendor/bootstrap.bundle.min.js
- static/vendor/bootstrap.bundle.min.js.map
- static/vendor/bootstrap.min.css
- static/vendor/bootstrap.min.css.map
- static/vendor/chart.umd.min.js
- static/vendor/chart.umd.min.js.map
- static/vendor/chartjs.LICENSE
- templates/403.html
- templates/404.html
- templates/500.html
- templates/base.html
- templates/core/audit.html
- templates/core/dashboard.html
- templates/core/module.html
- templates/core/no_access.html
- templates/core/profile.html
- templates/core/roadmap.html
- templates/core/settings.html
- templates/includes/form_fields.html
- templates/includes/pagination.html
- templates/layout.html
- templates/people/student_detail.html
- templates/people/student_list.html
- templates/registration/auth_base.html
- templates/registration/locked.html
- templates/registration/login.html
- templates/registration/password_reset_complete.html
- templates/registration/password_reset_confirm.html
- templates/registration/password_reset_done.html
- templates/registration/password_reset_email.txt
- templates/registration/password_reset_form.html
- templates/registration/password_reset_subject.txt
- tests/__init__.py
- tests/helpers.py
- tests/test_authentication.py
- tests/test_ci_security.py
- tests/test_configuration.py
- tests/test_foundation.py
- tests/test_permissions.py
- tests/test_repository.py

## School operations additions

Phase 2 adds academic forms, authorized services, management URLs/views and templates;
people admission/transition/directory/import services, forms and views; shared form/image
helpers; academic/core/people migrations; private image widgets; CSV cleanup management
command; operational/concurrency/migration tests; and docs/SCHOOL_OPERATIONS.md.
All existing first-party source remains in place. Generated previews, test logs,
private uploads and runtime database files remain excluded from the source set.

## Phase 3 attendance additions

The attendance app adds models, database record guards, calendar/rules,
selectors, transactional services, SQL reporting, CSV/PDF exports, routes and admin.
Attendance templates and static/js/attendance.js supply registers, calendars,
dashboards, requests/reviews, notices and reports. New tests cover attendance,
boundaries and concurrency. scripts/attendance_browser.py creates its own isolated
browser test database. docs/ATTENDANCE_POLICY.md documents the policy and workflows.
Runtime data, private files, test logs and screenshots remain ignored.


## Phase 4 examination files

- `examinations/__init__.py`
- `examinations/admin.py`
- `examinations/apps.py`
- `examinations/calculations.py`
- `examinations/demo.py`
- `examinations/exports.py`
- `examinations/forms.py`
- `examinations/migrations/0001_initial.py`
- `examinations/migrations/0002_history_guards.py`
- `examinations/migrations/0003_candidateamendment_examsession_retake_of_and_more.py`
- `examinations/migrations/0004_amendment_schedule_guards.py`
- `examinations/migrations/0005_examnotification_exam_recipient_date_idx_and_more.py`
- `examinations/migrations/__init__.py`
- `examinations/models.py`
- `examinations/reporting.py`
- `examinations/selectors.py`
- `examinations/services.py`
- `examinations/urls.py`
- `examinations/views.py`
- `templates/examinations/analytics.html`
- `templates/examinations/base.html`
- `templates/examinations/candidate.html`
- `templates/examinations/corrections.html`
- `templates/examinations/dashboard.html`
- `templates/examinations/form.html`
- `templates/examinations/marks.html`
- `templates/examinations/notifications.html`
- `templates/examinations/report.html`
- `templates/examinations/results.html`
- `templates/examinations/schedules.html`
- `templates/examinations/session.html`
- `templates/examinations/setup.html`
- `static/css/examinations.css`
- `static/js/examinations.js`
- `scripts/examination_browser.py`
- `tests/test_examinations.py`
- `tests/test_examination_boundaries.py`
- `tests/test_examination_concurrency.py`
- `docs/PHASE4_PLAN.md`
- `docs/EXAMINATION_POLICY.md`

Integration also updates managed examination grants, the gated demo command, Django
app/URL registration, existing academic/enrollment guards, the promotion form and
student/navigation links. The former examination placeholder regression now checks
the still-planned finance module. No later module was implemented.
