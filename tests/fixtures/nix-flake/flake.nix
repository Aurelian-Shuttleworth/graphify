{
  description = "Graphify test fixture flake — exercises all Nix extraction patterns";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    flake-parts.url = "github:hercules-ci/flake-parts";
  };

  outputs = inputs@{ self, nixpkgs, home-manager, flake-parts, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      constants = import ./constants.nix;
    in
    {
      nixosModules.default = import ./modules/default.nix;
      nixosModules.services-example = import ./modules/services/example.nix;
      nixosModules.programs-editor = import ./modules/programs/editor.nix;
      overlays.default = import ./overlays/default.nix;
      packages.${system} = {
        tool = pkgs.callPackage ./pkgs/tool/default.nix {};
      };
      homeManagerModules.default = import ./home-manager/default.nix;
    };
}
