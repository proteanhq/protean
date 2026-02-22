document.addEventListener("DOMContentLoaded", function() {
  var isDark = document.body.getAttribute("data-md-color-scheme") === "slate";

  var lightVars = {
    primaryColor: "#E6FAF8",
    primaryTextColor: "#0F4C5C",
    primaryBorderColor: "#0D9488",
    lineColor: "#0D9488",
    secondaryColor: "#F0F4F5",
    tertiaryColor: "#FAFBFC",
    signalColor: "#0F4C5C",
    signalTextColor: "#0F4C5C",
    noteBkgColor: "#E6FAF8",
    noteTextColor: "#0F4C5C",
    noteBorderColor: "#0D9488",
    actorBkg: "#E6FAF8",
    actorBorder: "#0D9488",
    actorTextColor: "#0F4C5C",
    activationBorderColor: "#0D9488",
    activationBkgColor: "#E6FAF8",
    sequenceNumberColor: "#FFFFFF",
    fontFamily: "Inter, sans-serif",
    fontSize: "14px",
  };

  var darkVars = {
    primaryColor: "#1E2D3D",
    primaryTextColor: "#F1F5F9",
    primaryBorderColor: "#5EEAD4",
    lineColor: "#2DD4BF",
    secondaryColor: "#1E2D3D",
    tertiaryColor: "#131A24",
    signalColor: "#F1F5F9",
    signalTextColor: "#F1F5F9",
    noteBkgColor: "#1E2D3D",
    noteTextColor: "#F1F5F9",
    noteBorderColor: "#5EEAD4",
    actorBkg: "#1E2D3D",
    actorBorder: "#5EEAD4",
    actorTextColor: "#F1F5F9",
    activationBorderColor: "#5EEAD4",
    activationBkgColor: "#1E2D3D",
    sequenceNumberColor: "#0A3640",
    fontFamily: "Inter, sans-serif",
    fontSize: "14px",
  };

  mermaid.initialize({
    startOnLoad: true,
    theme: "base",
    themeVariables: isDark ? darkVars : lightVars,
    securityLevel: "loose",
    sequence: {
      useMaxWidth: true,
      showSequenceNumbers: true,
    },
  });
});
