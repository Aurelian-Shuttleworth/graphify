{ config, lib, pkgs, ... }:

{
  imports = [
    ../modules/services/example.nix
    ../modules/programs/editor.nix
  ];

  home.stateVersion = "24.05";
  home.username = "testuser";
  home.homeDirectory = "/home/testuser";
}
