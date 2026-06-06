{ config, lib, pkgs, ... }:

let
  cfg = config.services.myApp;

  mkConfiguration = name: value: {
    inherit name;
    settings = value;
  };

  helpers = import ./helpers.nix;
  utils = import ./utils.nix { inherit lib; };

in {
  options.services.myApp = {
    enable = lib.mkEnableOption "My Application";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.myApp;
      description = "The myApp package to use";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "Port to listen on";
    };

    settings = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = {};
      description = "Additional settings";
    };

    configFile = lib.mkOption {
      type = lib.types.path;
      default = ./config.toml;
      description = "Path to the config file";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];

    systemd.services.myApp = {
      description = "My Application Service";
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        ExecStart = "${cfg.package}/bin/myapp --port ${toString cfg.port}";
        Restart = "always";
      };
    };

    users.users.myapp = {
      isSystemUser = true;
      group = "myapp";
      home = "/var/lib/myapp";
    };

    users.groups.myapp = {};

    networking.firewall.allowedTCPPorts =
      lib.optional (cfg.port != null) cfg.port;
  };
}
