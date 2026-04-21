Feature: Email allowlist enforcement
  The Firebase authentication middleware enforces a comma-separated
  allowlist from DJANGO_ALLOWED_USERS. A user whose email is in the
  allowlist is authenticated; a user whose email is not gets a 403.
  If the env var is empty or unset, the middleware refuses to start.

  Scenario: Allowed email is authenticated
    Given a Firebase session for email "test@example.com"
    When the user requests the home page
    Then the response status is 200

  Scenario: Disallowed email gets a 403
    Given a Firebase session for email "intruder@example.com"
    When the user requests the home page
    Then the response status is 403

  Scenario: Empty DJANGO_ALLOWED_USERS refuses to start
    Given DJANGO_ALLOWED_USERS is unset
    When the Firebase auth middleware is constructed
    Then it raises ImproperlyConfigured
