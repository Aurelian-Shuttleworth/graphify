{ config, lib, pkgs, ... }:

{
  imports = [
    ./services/example.nix
    ./programs/editor.nix
  ];
}
