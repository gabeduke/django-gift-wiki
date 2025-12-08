Feature: User Authentication and Profile
  As a user
  I want to manage my account
  So that I can access the gift wiki

  Scenario: Register a new account
    Given I am not logged in
    When I navigate to the signup page
    And I fill in the registration form with:
      | Username  | newuser    |
      | Email     | new@test.com |
      | Password  | testpass123 |
    And I submit the form
    Then I should be logged in
    And I should see my username on the page

  Scenario: Login with valid credentials
    Given I have an account with:
      | Username  | existinguser |
      | Password  | testpass123  |
    When I navigate to the login page
    And I enter my credentials
    And I submit the login form
    Then I should be logged in
    And I should see my username

  Scenario: Login with invalid credentials
    Given I have an account
    When I navigate to the login page
    And I enter wrong credentials
    And I submit the login form
    Then I should see an error message
    And I should not be logged in

  Scenario: View my profile
    Given I am logged in
    When I navigate to my profile
    Then I should see my user information
    And I should see my wishlists

  Scenario: Logout
    Given I am logged in
    When I click "Logout"
    Then I should be logged out
    And I should be redirected to the home page

