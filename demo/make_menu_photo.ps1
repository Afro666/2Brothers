# Deterministic typed menu for #1136. Run from any folder on Windows.
# Names match demo.seed's env recipes; covers are explicitly printed, never inferred.
Add-Type -AssemblyName System.Drawing
$menuImage = [System.Drawing.Bitmap]::new(1400, 1000)
$canvas = [System.Drawing.Graphics]::FromImage($menuImage)
$titleFont = [System.Drawing.Font]::new('Arial', 36)
$rowFont = [System.Drawing.Font]::new('Arial', 25)
try {
    $canvas.Clear([System.Drawing.Color]::White)
    $canvas.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $canvas.DrawString('Kitchen menu - 16-20 November 2026', $titleFont, [System.Drawing.Brushes]::Black, 65, 65)
    $rows = @(
        'Monday: Macaroni casserole - 120 covers',
        'Tuesday: Chicken rice - 100 covers',
        'Wednesday: Salmon soup - 110 covers',
        'Thursday: Meatballs potato - 90 covers',
        'Friday: Pasta cream chicken - 100 covers'
    )
    for ($menuIndex = 0; $menuIndex -lt $rows.Count; $menuIndex++) {
        $canvas.DrawString($rows[$menuIndex], $rowFont, [System.Drawing.Brushes]::Black, 65, (220 + 130 * $menuIndex))
    }
    $menuImage.Save((Join-Path $PSScriptRoot 'menu-photo.png'), [System.Drawing.Imaging.ImageFormat]::Png)
}
finally {
    $rowFont.Dispose()
    $titleFont.Dispose()
    $canvas.Dispose()
    $menuImage.Dispose()
}
