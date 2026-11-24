# 图 2 渲染脚本：从手写 SVG 生成 300dpi PNG + 13.5cm 预览
# 源文件：kaiti_fig2_innovation.svg（1594×1160；标题 64px=15.36pt，层级 54px=12.96pt，编号 42px=10.08pt）
# 用法：powershell -ExecutionPolicy Bypass -File make_kaiti_fig2.ps1
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing

$dir=$PSScriptRoot
$svg=Join-Path $dir 'kaiti_fig2_innovation.svg'
$png=Join-Path $dir 'kaiti_fig2_innovation.png'
$preview=Join-Path $dir 'kaiti_fig2_innovation_preview13_5cm.png'

$chrome=$null
foreach($p in @(
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
)){ if(Test-Path $p){ $chrome=$p; break } }
if(-not $chrome){ throw '未找到 Chrome/Edge，无法渲染 SVG' }

$uri='file:///' + ($svg -replace '\\','/')
$udd=Join-Path $env:TEMP ('kaiti_fig2_'+[guid]::NewGuid().ToString('N'))
$sout=Join-Path $env:TEMP ('kaiti_fig2_out_'+[guid]::NewGuid().ToString('N')+'.log')
$serr=Join-Path $env:TEMP ('kaiti_fig2_err_'+[guid]::NewGuid().ToString('N')+'.log')
$args=@('--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run',
  "--user-data-dir=$udd",'--force-device-scale-factor=1','--window-size=1594,1160',
  "--screenshot=$png",$uri)
$proc=Start-Process -FilePath $chrome -ArgumentList $args -Wait -PassThru -NoNewWindow -RedirectStandardOutput $sout -RedirectStandardError $serr
Remove-Item $sout,$serr -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 600
if(-not (Test-Path $png)){ throw 'Chrome 未生成 PNG' }

# 写入 300dpi 元数据（像素尺寸不变）
$src=[System.Drawing.Image]::FromFile($png)
$bmp=New-Object System.Drawing.Bitmap($src.Width,$src.Height)
$g=[System.Drawing.Graphics]::FromImage($bmp)
$g.DrawImage($src,0,0,$src.Width,$src.Height)
$g.Dispose(); $src.Dispose()

# 强制纯灰阶：消除浏览器次像素抗锯齿带来的彩色边缘
$rect=New-Object System.Drawing.Rectangle(0,0,$bmp.Width,$bmp.Height)
$data=$bmp.LockBits($rect,[System.Drawing.Imaging.ImageLockMode]::ReadWrite,[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$n=$data.Stride*$data.Height
$buf=New-Object byte[] $n
[System.Runtime.InteropServices.Marshal]::Copy($data.Scan0,$buf,0,$n)
for($i=0;$i -lt $n;$i+=4){
  $v=[int](0.299*$buf[$i+2]+0.587*$buf[$i+1]+0.114*$buf[$i])
  $buf[$i]=$v; $buf[$i+1]=$v; $buf[$i+2]=$v
}
[System.Runtime.InteropServices.Marshal]::Copy($buf,0,$data.Scan0,$n)
$bmp.UnlockBits($data)

$bmp.SetResolution(300,300)
$tmp=Join-Path $env:TEMP ('kaiti_fig2_'+[guid]::NewGuid().ToString('N')+'.png')
$bmp.Save($tmp,[System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Copy-Item $tmp $png -Force
Remove-Item $tmp -Force

# 13.5cm 预览（96dpi 下 13.5cm ≈ 510px）
$img=[System.Drawing.Image]::FromFile($png)
$pw=510; $ph=[int]($img.Height*$pw/$img.Width)
$pre=New-Object System.Drawing.Bitmap($pw,$ph)
$pg=[System.Drawing.Graphics]::FromImage($pre)
$pg.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$pg.DrawImage($img,0,0,$pw,$ph)
$pg.Dispose(); $img.Dispose()
$pre.Save($preview,[System.Drawing.Imaging.ImageFormat]::Png)
$pre.Dispose()

Remove-Item $udd -Recurse -Force -ErrorAction SilentlyContinue
$i=[System.Drawing.Image]::FromFile($png)
Write-Output ('OK  ' + $png + '  ' + (Get-Item $png).Length + ' bytes  ' + $i.Width + 'x' + $i.Height + ' = ' + [Math]::Round($i.Width/300*2.54,2) + ' x ' + [Math]::Round($i.Height/300*2.54,2) + ' cm @' + [int]$i.HorizontalResolution + 'dpi')
$i.Dispose()
