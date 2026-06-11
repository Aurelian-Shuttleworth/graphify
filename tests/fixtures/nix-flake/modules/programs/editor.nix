{ config, lib, pkgs, ... }:

let
  inherit (lib) mkOption mkEnableOption mkIf types;

  cfg = config.programs.editor;
in
{
  options.programs.editor = {
    enable = mkEnableOption "editor configuration";

    package = mkOption {
      type = types.package;
      default = pkgs.vim;
      description = "The editor package.";
    };

    defaultEditor = mkOption {
      type = types.bool;
      default = true;
      description = "Whether to set this as the default editor.";
    };

    plugins = mkOption {
      type = types.listOf (types.submodule {
        options = {
          name = mkOption {
            type = types.str;
            description = "Plugin name.";
          };
          src = mkOption {
            type = types.package;
            description = "Plugin source package.";
          };
        };
      });
      default = [];
      description = "List of editor plugins.";
    };

    extraConfig = mkOption {
      type = types.lines;
      default = "";
      description = "Extra configuration lines.";
    };
  };

  config = mkIf cfg.enable {
    home.packages = [ cfg.package ];

    home.sessionVariables = mkIf cfg.defaultEditor {
      EDITOR = "${cfg.package}/bin/${cfg.package.pname}";
    };
  };
}
