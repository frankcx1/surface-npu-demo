# Create self-signed cert for MSIX signing (CN=FrankBu)
$existing = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq 'CN=FrankBu' }
if ($existing) {
    Write-Host "Certificate already exists:"
    Write-Host "  Thumbprint: $($existing.Thumbprint)"
    Write-Host "  Subject: $($existing.Subject)"
    Write-Host "  Expires: $($existing.NotAfter)"
} else {
    Write-Host "Creating self-signed certificate for CN=FrankBu..."
    $cert = New-SelfSignedCertificate -Type Custom -Subject 'CN=FrankBu' -KeyUsage DigitalSignature -FriendlyName 'NPU Vision Service Dev' -CertStoreLocation 'Cert:\CurrentUser\My' -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
    Write-Host "  Thumbprint: $($cert.Thumbprint)"
    Write-Host "  Subject: $($cert.Subject)"
    $existing = $cert
}

# Export and trust -- but DO NOT clobber an existing .cer with a different thumbprint.
# This file lives in OneDrive and is shared across multiple demo devices; overwriting it
# breaks MSIX trust on the device whose cert it currently matches.
$certPath = Join-Path $PSScriptRoot 'FrankBu.cer'
$shouldExport = $true
if (Test-Path $certPath) {
    try {
        $existingFile = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certPath)
        if ($existingFile.Thumbprint -eq $existing.Thumbprint) {
            Write-Host "Certificate file already exported (matching thumbprint $($existing.Thumbprint))"
            $shouldExport = $false
        } else {
            Write-Host "WARNING: $certPath has thumbprint $($existingFile.Thumbprint) -- different from this device's cert ($($existing.Thumbprint))."
            Write-Host "         Refusing to overwrite. The MSIX in this repo is signed by the OTHER thumbprint."
            Write-Host "         If you want to regenerate from scratch, delete $certPath and re-run."
            $shouldExport = $false
        }
    } catch {
        Write-Host "WARNING: $certPath exists but isn't a valid cert. Refusing to overwrite."
        $shouldExport = $false
    }
}
if ($shouldExport) {
    Export-Certificate -Cert $existing -FilePath $certPath | Out-Null
    Write-Host "Certificate exported to $certPath"
}

# Trust it in BOTH stores (requires admin - may fail)
# MSIX self-signed packages require the cert in both Trusted Root CA and Trusted People
try {
    Import-Certificate -FilePath $certPath -CertStoreLocation 'Cert:\LocalMachine\Root' | Out-Null
    Write-Host "Certificate trusted in LocalMachine\Root (Trusted Root CA)"
} catch {
    Write-Host "WARNING: Could not add cert to Root store (needs admin)."
}
try {
    Import-Certificate -FilePath $certPath -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople' | Out-Null
    Write-Host "Certificate trusted in LocalMachine\TrustedPeople"
} catch {
    Write-Host "WARNING: Could not add cert to TrustedPeople store (needs admin)."
}

# Verify both stores
$inRoot = Get-ChildItem 'Cert:\LocalMachine\Root' | Where-Object { $_.Subject -eq 'CN=FrankBu' }
$inPeople = Get-ChildItem 'Cert:\LocalMachine\TrustedPeople' | Where-Object { $_.Subject -eq 'CN=FrankBu' }
if ($inRoot -and $inPeople) {
    Write-Host "Certificate installed in both required stores."
} else {
    Write-Host "WARNING: Certificate missing from one or both stores. Run as Administrator:"
    Write-Host "  Import-Certificate -FilePath '$certPath' -CertStoreLocation 'Cert:\LocalMachine\Root'"
    Write-Host "  Import-Certificate -FilePath '$certPath' -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople'"
}

Write-Host "`nThumbprint for signing: $($existing.Thumbprint)"
