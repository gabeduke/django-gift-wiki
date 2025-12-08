Feature: Data Integrity and Validation
  As the system
  I want to maintain data consistency
  So that the application is reliable

  Background:
    Given users Alice, Bob, and Charlie exist
    And Alice has a wishlist "Christmas 2025"

  # Referential Integrity
  Scenario: Deleting Wishlist Cascades Items
    Given Alice has 3 items in "Christmas 2025"
    When Alice deletes "Christmas 2025"
    Then all 3 items should be deleted from the database
    And they should no longer exist

  Scenario: Deleting User Does Not Delete Wishlists
    Given Alice has a wishlist "Christmas 2025"
    When Alice's account is deleted
    Then "Christmas 2025" should still exist
    But it should be marked as orphaned

  # Data Validation
  Scenario: Item Price Validation
    Given I am creating an item
    When I enter a price "abc"
    Then I should see a validation error
    And the item should NOT be created
    When I enter a valid price "29.99"
    Then the item should be created

  Scenario: Required Fields Enforcement
    Given I am creating a wishlist
    When I submit without a title
    Then I should see a validation error
    And the wishlist should NOT be created
    When I submit with a title
    Then the wishlist should be created

  # Business Logic
  Scenario: Purchase Tracking
    Given Alice has an item "New bike" with price "100.00"
    When Bob marks "New bike" as purchased
    Then "New bike".purchased_by should equal Bob
    And "New bike".purchased should be True
    And "New bike".updated_by should equal Bob

  Scenario: Update Tracking
    Given Alice has an item "New bike"
    When Alice updates "New bike" to "Blue bike"
    Then "New bike".updated_by should equal Alice
    And "New bike".updated_at should be updated

  # Soft Delete Integrity
  Scenario: Deleted Items Filtered from Queries
    Given Alice has 3 items in her wishlist
    And Alice deletes one item
    When viewing the wishlist
    Then only 2 items should be displayed
    And the deleted item should not appear

  Scenario: Multiple Operations on Same Item
    Given Alice has an item "New bike"
    When Bob tries to purchase "New bike"
    And at the same time Alice tries to delete "New bike"
    Then the database should remain consistent
    And either operation should succeed but not both

