Feature: Core Gift Wiki Application Behavior
  As a gift coordinator
  I want the application to enforce clear ownership and purchase rules
  So that gift giving is clear and organized

  Background:
    Given I am logged in as "Alice"
    And there is a user "Bob" 
    And Alice has a family "The Smiths"

  # Core Ownership Rules
  Scenario: Wishlist Ownership
    Given Alice creates a wishlist "Christmas 2025"
    When Alice views her wishlists
    Then Alice should see "Christmas 2025"
    And "Christmas 2025" should be marked as owned by Alice

  Scenario: Only Owner Can Edit Items
    Given Alice has a wishlist "Christmas 2025"
    And Alice adds an item "New bike" to "Christmas 2025"
    When Bob tries to edit "New bike"
    Then Bob should see an error message
    And the item should remain unchanged
    When Alice tries to edit "New bike"
    Then Alice should be able to update the item

  Scenario: Only Owner Can Delete Items
    Given Alice has an item "New bike" in her wishlist
    When Bob tries to delete "New bike"
    Then Bob should not see a delete button
    And Bob cannot delete the item
    When Alice tries to delete "New bike"
    Then Alice should be able to delete it
    And "New bike" should be marked as deleted (soft delete)

  # Purchase Behavior
  Scenario: Marking Items as Purchased - Owner View
    Given Alice has an item "New bike" in her wishlist
    When Bob marks "New bike" as purchased
    Then Bob should see "Item marked as purchased"
    When Alice views her wishlist
    Then Alice should still see "New bike" in the list
    And Alice should see that Bob purchased it
    And Alice should still be able to edit "New bike"

  Scenario: Marking Items as Purchased - Purchaser View
    Given Alice has an item "New bike" in her wishlist
    When Bob marks "New bike" as purchased
    Then Bob's name should be stored as the purchaser
    When other users view the wishlist
    Then "New bike" should show as purchased
    And they should see Bob purchased it
    And they should NOT be able to purchase it again

  Scenario: Owners Can Purchase Their Own Items
    Given Alice has an item "New bike" in her wishlist
    When Alice marks "New bike" as purchased
    Then Alice should see "Item marked as purchased"
    And the item should be marked as purchased
    And purchased_by should be set to Alice

  Scenario: Preventing Duplicate Purchases
    Given Alice has an item "New bike" in her wishlist
    When Bob marks "New bike" as purchased
    Then "New bike" should have purchased_by set to Bob
    When Charlie tries to mark "New bike" as purchased
    Then Charlie should see that Bob already purchased it
    And Charlie cannot mark it as purchased

  # Purchase Information Visibility (Simplified - Everyone Can See)
  Scenario: Purchase Information Visibility
    Given Alice has an item "New bike" in her wishlist
    And Bob has marked "New bike" as purchased
    When Alice views her wishlist
    Then Alice should see "New bike" in the list
    And Alice should see that Bob purchased it
    And Alice should see Bob's name
    When Bob views the wishlist
    Then Bob should see "New bike" as purchased by Bob
    When Charlie views the wishlist
    Then Charlie should see "New bike" as purchased
    And Charlie should see Bob's name

  # Wishlist Management
  Scenario: Wishlist Deletion
    Given Alice has a wishlist "Christmas 2025"
    When Alice deletes "Christmas 2025"
    Then the wishlist should be permanently deleted
    And all items in "Christmas 2025" should be deleted
    And the wishlist should not appear in any lists

  Scenario: Cannot Delete Another User's Wishlist
    Given Alice has a wishlist "Christmas 2025"
    When Bob tries to delete "Christmas 2025"
    Then Bob should not see a delete button
    And the wishlist should remain in the database

  # Item Management
  Scenario: Soft Delete of Items
    Given Alice has an item "New bike" in her wishlist
    When Alice deletes "New bike"
    Then "New bike" should have is_deleted=True
    And "New bike" should not appear in the wishlist view
    But "New bike" should still exist in the database
    And Alice should see "Item deleted successfully"

  Scenario: Viewing All Items (Including Deleted)
    Given Alice has deleted an item "Old toy"
    When viewing the database directly
    Then "Old toy" should exist with is_deleted=True
    But "Old toy" should not appear in the wishlist UI

