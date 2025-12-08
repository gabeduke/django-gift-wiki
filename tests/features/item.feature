Feature: Item Management
  As a user
  I want to manage items on my wishlists
  So that others can see what I want

  Background:
    Given I am logged in as a user
    And I have a wishlist

  Scenario: Add an item to a wishlist
    Given I am viewing my wishlist
    When I click "Add Item"
    And I fill in the item form with:
      | Name        | Test Item     |
      | Description | Item details  |
      | Price       | 29.99         |
    And I submit the form
    Then I should see "Item added successfully"
    And the item should appear in my wishlist

  Scenario: Edit an item
    Given I have an item in my wishlist
    When I click "Edit" on the item
    And I update the name to "Updated Item"
    And I save the changes
    Then I should see "Item updated successfully"
    And the item should show "Updated Item"

  Scenario: Delete an item
    Given I have an item in my wishlist
    When I click "Delete" on the item
    And I confirm the deletion
    Then I should see "Item deleted successfully"
    And the item should no longer appear

  Scenario: Mark an item as purchased
    Given another user has an item on their wishlist
    When I click "Mark as Purchased" on the item
    Then I should see "Item marked as purchased"
    And the item should show as purchased to other users
    But the owner should not see the purchased status

  Scenario: Cannot purchase own items
    Given I have an item in my wishlist
    When I try to mark my own item as purchased
    Then I should see an error message
    And the item should not be marked as purchased

