let
  inherit (builtins) attrNames;

  mkHelper = name: value: {
    inherit name;
    formattedValue = toString value;
  };

  concatLines = lines: builtins.concatStringsSep "\n" lines;
in
{
  inherit mkHelper concatLines;

  defaultTimeout = 30;
  defaultRetries = 3;
}
