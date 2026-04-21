Feature: Runtime feature flags
  Two feature flags gate optional behavior: STEWARD_PROXY_ENABLED controls
  whether a wishlist's dependent ("steward") may edit the list, and
  PROFILE_PICTURE_ENABLED controls whether the profile page renders the
  picture upload field.

  Scenario: Steward proxy on — dependent can open the edit page
    Given the other user is the dependent on the wishlist
    And STEWARD_PROXY_ENABLED is on
    When the dependent opens the wishlist edit page
    Then the response status is 200

  Scenario: Steward proxy off — dependent cannot open the edit page
    Given the other user is the dependent on the wishlist
    And STEWARD_PROXY_ENABLED is off
    When the dependent opens the wishlist edit page
    Then the response status is 302

  Scenario: Profile picture flag on — profile page renders the upload field
    Given PROFILE_PICTURE_ENABLED is on
    When the user opens the profile page
    Then the page shows the profile picture field

  Scenario: Profile picture flag off — profile page hides the upload field
    Given PROFILE_PICTURE_ENABLED is off
    When the user opens the profile page
    Then the page does not show the profile picture field
