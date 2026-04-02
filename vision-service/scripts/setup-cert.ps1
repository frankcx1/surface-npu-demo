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

# Export and trust
$certPath = Join-Path $PSScriptRoot 'FrankBu.cer'
Export-Certificate -Cert $existing -FilePath $certPath | Out-Null
Write-Host "Certificate exported to $certPath"

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
