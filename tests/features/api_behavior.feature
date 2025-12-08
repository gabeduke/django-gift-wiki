Feature: API and Response Behavior
  As a developer
  I want clear API responses
  So that I can build reliable frontends

  Background:
    Given I am logged in as "Alice"
    And there is a user "Bob"
    And Alice has a wishlist "Christmas 2025"

  # HTTP Status Codes
  Scenario: Successful Item Creation Returns 302
    Given I am on the add item page for "Christmas 2025"
    When I submit valid item data
    Then I should receive HTTP status 302 (redirect)
    And I should be redirected to the wishlist detail page

  Scenario: Successful Item Update Returns 302
    Given Alice has an item "New bike" in her wishlist
    When Alice updates "New bike" with new description
    Then the response should be HTTP status 302
    And the item should be updated in the database

  Scenario: Unauthorized Access Returns 403 or Redirect
    Given Alice has a wishlist "Christmas 2025"
    When Bob tries to edit an item without permission
    Then Bob should be denied access
    And the response should be HTTP status 403 or redirect

  # JSON Responses
  Scenario: AJAX Item Addition Returns JSON
    Given I make an AJAX request to add an item
    When the request succeeds
    Then I should receive JSON with item ID and name
    And the response should contain:
      | Field | Type   |
      | id    | number |
      | name  | string |

  # Error Handling
  Scenario: Invalid Form Data Shows Errors
    Given I am on the add item page
    When I submit the form with invalid data
    Then I should see validation errors on the page
    And the form should be re-displayed with errors
    And the item should NOT be created

  Scenario: Non-existent Item Returns 404
    Given I try to access item ID 99999
    When the request is processed
    Then I should receive HTTP status 404
    And I should see a "Not Found" message

  # Authentication
  Scenario: Unauthenticated User Cannot Create Wishlist
    Given I am not logged in
    When I try to create a wishlist
    Then I should be redirected to the login page
    And the wishlist should NOT be created

  Scenario: Authenticated User Can Create Wishlist
    Given I am logged in as Alice
    When I create a wishlist
    Then the wishlist should be created
    And I should see a success message
    And the wishlist should appear in my profile

  # Data Integrity
  Scenario: Wishlist Created with Required Fields
    Given I am logged in as Alice
    When I create a wishlist with only a title
    Then the wishlist should be created
    And the owner should be set to Alice
    And family_name should be set (if provided)

  Scenario: Item Created with Wishlist Reference
    Given I have a wishlist "Christmas 2025"
    When I add an item "New bike"
    Then "New bike" should have wishlist reference
    And "New bike" should have is_deleted=False
    And "New bike" should have purchased=False

