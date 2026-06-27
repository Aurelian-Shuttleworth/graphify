# V3 Nix extraction test fixture
# Tests: with-list items, imports arrays, inherit (pkgs), nested with
{ config, lib, pkgs, ... }:

let
  # Basic with-pkgs list (WS1: list item extraction)
  containerTools = with pkgs; [
    crane        # registry interaction
    cosign       # image signing
    dive         # layer inspector
  ];

  # With lib; list — should use lib scope, not pkgs
  utilFunctions = with lib; [
    mkOption
    mkEnableOption
    mkIf
  ];

  # Nested with — innermost scope wins
  nestedExample = with pkgs; with lib; [
    mkMerge
    mkForce
  ];

  # Qualified references inside list (select_expression)
  qualifiedTools = with pkgs; [
    rubyPackages_3_4.ruby-lsp
    nodePackages.typescript-language-server
  ];

  # Inline derivations (apply_expression in list)
  customTools = with pkgs; [
    (writeShellApplication {
      name = "my-tool";
      runtimeInputs = [ jq curl ];
      text = ''echo hello'';
    })
  ];

  # Inherit from pkgs (WS4: inherit scope resolution)
  inherit (pkgs) git curl wget;

  # Inherit from lib (should NOT create depends_on)
  inherit (lib) mkOption mkEnableOption;

  # DevOps tools imported from separate file
  devOpsTools = import ./packages/devops.nix { inherit pkgs; };

in {
  # NixOS-style imports array (WS2: imports array extraction)
  imports = [
    ./modules/networking.nix
    ./modules/security.nix
    ./modules/monitoring.nix
  ];

  # Config section
  config = lib.mkIf config.services.myApp.enable {
    environment.systemPackages = containerTools ++ customTools;
    networking.firewall.enable = true;
  };

  # With-list inside config body
  extraPackages = with pkgs; [
    htop
    tmux
  ];
}
