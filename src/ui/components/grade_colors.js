// Shared grade-badge colouring for the song picker, the library and anything
// else that shows a "Grade N" level string.
.pragma library

// Gradient: Green -> Yellow -> Orange -> Red
var PALETTE = [
    "#4CAF50", "#8BC34A", "#CDDC39", "#FFEB3B", "#FFC107",
    "#FF9800", "#FF5722", "#F44336", "#D32F2F", "#B71C1C"
];

function forGrade(level) {
    if (!level)
        return "#666666";
    var match = ("" + level).match(/Grade (\d+)/);
    if (!match)
        return "#666666";
    var g = parseInt(match[1]);
    return PALETTE[Math.max(0, Math.min(g - 1, 9))];
}
