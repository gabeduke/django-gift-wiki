Feature: Wishlist Management
  As a user
  I want to manage my wishlists
  So that I can share my gift preferences with family

  Background:
    Given I am logged in as a user
    And I have a family group created

  Scenario: Create a new wishlist
    Given I am on the create wishlist page
    When I fill in the wishlist form with:
      | Title       | Test Wishlist |
      | Description | My gift list  |
    And I submit the form
    Then I should see "Wishlist created successfully"
    And I should be on my wishlist detail page

  Scenario: View my wishlists
    Given I have created a wishlist
    When I navigate to the home page
    Then I should see a list of my wishlists
    And each wishlist should display:
      | Title       | Description  |
      | Test Item 1 | First list   |

  Scenario: Edit a wishlist
    Given I have created a wishlist
    When I navigate to the wishlist
    And I click "Edit"
    And I update the title to "Updated Title"
    And I save the changes
    Then I should see "Updated Title" on the page

  Scenario: Delete a wishlist
    Given I have created a wishlist
    When I navigate to the wishlist
    And I click "Delete"
    And I confirm the deletion
    Then I should see "Wishlist deleted successfully"
    And the wishlist should no longer exist

  Scenario: View another user's wishlist
    Given another user has created a wishlist
    When I navigate to their wishlist
    Then I should see the wishlist items
    But I should not see controls to edit or delete

  Scenario: Cannot delete another user's wishlist
    Given another user has created a wishlist
    When I try to delete their wishlist
    Then I should see an error message
    And the wishlist should still exist

