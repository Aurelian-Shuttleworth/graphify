{ config, lib, pkgs, ... }:

let
  inherit (lib) mkOption mkEnableOption mkIf types;

  cfg = config.services.example;
in
{
  options.services.example = {
    enable = mkEnableOption "example service";

    package = mkOption {
      type = types.package;
      default = pkgs.hello;
      description = "The package to use for the example service.";
    };

    port = mkOption {
      type = types.port;
      default = 8080;
      description = "The port to listen on.";
    };

    settings = mkOption {
      type = types.submodule {
        options = {
          verbose = mkOption {
            type = types.bool;
            default = false;
            description = "Enable verbose logging.";
          };

          logLevel = mkOption {
            type = types.enum [ "debug" "info" "warn" "error" ];
            default = "info";
            description = "The log level.";
          };

          allowedHosts = mkOption {
            type = types.listOf types.str;
            default = [ "localhost" ];
            description = "Allowed hosts.";
          };
        };
      };
      default = {};
      description = "Service settings.";
    };

    extraConfig = mkOption {
      type = types.attrsOf types.str;
      default = {};
      description = "Extra configuration key-value pairs.";
    };
  };

  config = mkIf cfg.enable {
    systemd.services.example = {
      description = "Example Service";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        ExecStart = "${cfg.package}/bin/hello --port ${toString cfg.port}";
        Restart = "always";
      };
    };

    environment.systemPackages = [ cfg.package ];
  };
}
