# SSH için HTTP(S) Relay Tüneli: Katı Güvenlik Duvarları Arkasında Sıfır Veri Kaybıyla Uzaktan Erişim

Yüksek güvenlikli, kısıtlayıcı kurumsal ağlar, Taşıyıcı Düzeyinde NAT (CGNAT) ve izole edilmiş ağlar için özel olarak tasarlanmış, kayıplara dayanıklı bir TCP-over-HTTPS tünelleme çözümü. Bu sistem; port yönlendirme (port forwarding), sabit veya genel (public) bir IP adresine ihtiyaç duymadan, paket kaybı yaşamaksızın etkileşimli SSH kabuk oturumları ve yüksek hızlı SFTP/SCP dosya aktarımları yapmanızı sağlar.

---

> [!TIP]
> **English Documentation:** You can read the English version in [README.md](README.md).

---

## Sorun ve Çözüm

Pek çok kurumsal, kampüs veya izole üretim ortamında:
* Port 22 gibi standart dışı portlara yapılan giden (outbound) TCP bağlantıları, Yeni Nesil Güvenlik Duvarları (NGFW) ve Derin Paket İnceleme (DPI) araçlarıyla engellenir.
* Dışarıdan gelen (inbound) tüm portlar kesinlikle yasaktır ve NAT geçişi engellenir.
* Doğrudan uçtan uca tüneller (WireGuard, OpenVPN, standart reverse SSH tünelleri) hız kısıtlamasına (throttling) takılır, engellenir veya kesilir.

**Bu Proje Nasıl Çözüyor:**
Sistem, çevre güvenlik duvarlarıyla mücadele etmek yerine ham SSH TCP paketlerini standart, uyumlu HTTPS `POST` ve `GET` istekleri (`application/octet-stream`) içerisine paketler (encapsulation). Nötr ve hafif bir web sunucusu üzerinden iki yönlü bir köprü kurar:

```text
[ Yerel İstemci (Client) ]           [ Genel Aktarım Sunucusu (Relay) ]     [ Hedef Sunucu (Target) ]
 (Kişisel Laptop / PC)                     (Harici PHP Sunucusu)            (NAT Arkasındaki İş İstasyonu)
        |                                      |                                       |
   Yerel SSH İstemcisi                         |                                  OpenSSH Daemon
(ssh user@127.0.0.1:2222)                      |                                  (127.0.0.1:22)
        |                                      |                                       |
    ssh.py (client)    === Dışa Doğru HTTPS ==> api.php <== Dışa Doğru Long-Poll === ssh.py (server)
                       (Port 443 / TLS 1.3)            (Port 443 / TLS 1.3)
```

Her iki uç nokta da 443 numaralı port üzerinden **dışa doğru (outbound)** bağlantı başlatır. Kurumsal güvenlik duvarları, proxy'ler ve DPI filtreleri açısından tüm trafik, geçerli bir tarayıcı `User-Agent` başlığına sahip normal web sayfalarını geziyormuş gibi görünür.

---

## Altyapı Gereksinimleri (3 Temel Bileşen)

Tüneli kurmak için tam olarak 3 düğüme (node) ihtiyacınız vardır:

1. **Bir Adet Harici Aktarım Sunucusu (Web Host / Relay)**:
   * Standart PHP 7.4+ çalıştırabilen herhangi bir sunucu (cPanel, paylaşımlı hosting, Apache, Nginx, VPS, Docker).
   * `root`/sudo yetkisi, özel sistem servisleri veya açık özel portlar **gerektirmez**.
   * Yalnızca tek bir bağımsız betik çalıştırır: `api.php`.
   * Geçerli ve aktif bir SSL/TLS sertifikasına sahip olmalıdır (Port 443 üzerinde HTTPS).

2. **Hedef Makine (Yönetilmek İstenen Uzak Bilgisayar)**:
   * Güvenli ağın içinde bulunan ve erişmek istediğiniz bilgisayar (ör. Ubuntu, Debian, CentOS, macOS, WSL).
   * `127.0.0.1:22` üzerinde standart OpenSSH sunucusunu (`sshd`) çalıştırır.
   * `ssh.py` dosyasını `--mode server` modunda çalıştırır.

3. **İstemci Makine (Kendi Yerel Bilgisayarınız)**:
   * Fiziksel olarak başında oturduğunuz bilgisayar (Windows, macOS veya Linux).
   * Standart bir SSH istemcisi çalıştırır (`ssh` komutu, PuTTY, VS Code Remote SSH, WinSCP vb.).
   * `ssh.py` dosyasını `--mode client` modunda çalıştırır.

---

## Temel Özellikler ve Mühendislik Detayları

* **Sıfır Veri Kaybı ve Güvenilirlik Garantisi**: Atomik kuyruk takibiyle birlikte sıralı paket indeksleme (`seq=0, 1, 2...`) kullanır. Paketler yalnızca karşı tarafta tamamen tüketildikten sonra onaylanır (ack) ve kuyruktan kaldırılır; böylece tuş vuruşu kaybı veya dosya bozulmaları önlenir.
* **Mikro-Toplu Paketleme (Micro-Batching)**: SCP/SFTP transferleri veya yoğun terminal çıktıları gibi yüksek veri akışlarında, soket paketleri tek bir birleşik HTTP yükünde (istek başına 25 pakete kadar) paketlenerek HTTP başlık yükü ve gecikme ciddi oranda düşürülür.
* **Duyarlı Long-Polling Motoru**: HTTP 204 keep-alive ve 20 saniyelik dinleyicilere sahip ultra hızlı mikrosaniye yoklama aralıkları ile terminalde neredeyse anlık etkileşim tepkisi sağlar.
* **Gelişmiş DPI ve WAF Gizliliği**: Gerçek Google Chrome tarayıcı isteklerini birebir taklit eder (`User-Agent`, standart TLS, HTTP keep-alive, standart MIME tipleri).
* **Kendi Kendini Onaran Bağlantı Havuzu**: Geçici ağ kopmalarını tolere etmek için üssel geri çekilme (exponential backoff) ve otomatik yeniden deneme mekanizmalarına sahip kalıcı HTTP oturum havuzu kullanır.
* **Otomatik Oturum Temizliği**: Bağlantı koptuğunda tamamlanan oturum tamponlarını ve geçici kuyruk klasörlerini otomatik olarak temizler, sunucuda disk şişmesini engeller.

---

## Ağ Sorunlarını Giderme ve DPI Atlama (Önemli Tavsiyeler)

Bazı son derece katı ağlarda (kurumsal proxy'ler, derin paket inceleme güvenlik duvarları veya bölgesel sansür sistemleri), **Hedef Sunucu** (`--mode server`) üzerindeki long-polling HTTPS istekleri zaman aşımına uğrayabilir veya kesintiye uğrayabilir.

Eğer hedef makinenizde `ssh.py --mode server` çalışmasına rağmen akış kurulamıyor veya paket düşüyorsa:

### Önerilen Çözüm: Hedef Bilgisayara Cloudflare WARP / Hızlı VPN
Yalnızca **hedef makinenin kendisine** hızlı bir tünel/VPN kurmanız yeterlidir:
1. **Cloudflare WARP (Tavsiye Edilen)**:
   * Ücretsiz, hafif ve özellikle kurumsal çıkış yönlendirmeleri için optimize edilmiştir.
   * Linux/Ubuntu üzerinde:
     ```bash
     # cloudflare-warp kurulumu
     sudo apt-get install cloudflare-warp
     warp-cli register
     warp-cli connect
     ```
   * WARP, hedef bilgisayarın dışarı giden HTTPS trafiğini Cloudflare'in WireGuard tabanlı uç ağına sararak kurumsal proxy filtrelemelerini ve ISP kısıtlamalarını tamamen aşar.
2. **Alternatif Olarak Hızlı WireGuard / Shadowsocks**:
   * Hedef bilgisayarda düşük gecikmeli herhangi bir WireGuard bağlantısı veya hafif bir çıkış proxy'si çalıştırmak, aradaki güvenlik duvarlarının neden olduğu paket düşüşlerini anında çözer.
   * **Not:** Kendi istemci bilgisayarınız relay domainine erişebildiği sürece istemci tarafında VPN açmanıza gerek yoktur.

### Ek Web Sunucusu İpuçları
* **Web Sunucusunda Proxy Buffering'i Kapatın**: `api.php` dosyasını Nginx veya Apache arkasında barındırıyorsanız, paketlerin gecikmesiz akabilmesi için çıktı tamponlamasını devre dışı bırakın (`proxy_buffering off;`).
* **Cloudflare CDN Ayarları**: Eğer relay alan adınız Cloudflare arkasındaysa, `/ssh/api.php` yolunda POST isteklerini tamponlayan kuralları kapatın ve bu yol için önbelleği (caching) devre dışı bırakın.
* **Keep-Alive Yapılandırması**: Etkileşimli SSH tuş vuruşlarının gecikmesini önlemek için `TCP_NODELAY` ayarını açık tutun (`ssh.py` içinde varsayılan olarak açıktır).

---

## Proje Dizin Yapısı

```text
.
├── api.php             # Web sunucunuza yüklenecek hafif PHP relay API dosyası
├── ssh.py              # İstemci, sunucu ve test modlarını yöneten çok kanallı (multi-threaded) Python köprüsü
├── requirements.txt    # Python bağımlılıkları (requests, urllib3)
├── .env.example        # Kimlik bilgileri için örnek ortam değişkenleri şablonu
├── .gitignore          # Loglar, sanal ortamlar ve geçici dosyalar için git hariç tutma kuralları
├── LICENSE             # MIT Lisans dosyası
├── README.md           # İngilizce teknik dokümantasyon
└── README_TR.md        # Türkçe teknik dokümantasyon
```

---

## Adım Adım Kurulum ve Dağıtım

### 1. Adım: PHP Relay Sunucusunun Kurulumu (Harici Web Sunucu)

1. `api.php` dosyasını web sunucunuza yükleyin (örneğin `public_html/ssh/api.php` konumuna yükleyerek `https://alan-adiniz.com/ssh/api.php` adresinden erişilebilir hale getirin).
2. PHP'nin geçici veri depolama klasörlerini (`.relay_data/` dizini) oluşturabilmesi için yazma izinlerinin olduğunu doğrulayın.
3. **Veri Tamponunu Güvene Alın**: `.relay_data/` klasörüne web üzerinden doğrudan erişimi engellemek için bir `.htaccess` dosyası koyun veya web sunucunuzda engelleyin:
   ```apache
   # Apache (.relay_data/ klasörü içinde veya kök dizinde .htaccess)
   <Directory ".relay_data">
       Require all denied
   </Directory>
   ```
4. Gizli kimlik doğrulama anahtarınızı (token) belirleyin:
   * **Önerilen**: Web sunucunuzda ortam değişkeni (environment variable) olarak tanımlayın:
     ```bash
     RELAY_AUTH_TOKEN="buraya_cok_guclu_rastgele_bir_token_yazin"
     ```
   * **Alternatif**: Anahtarı doğrudan `api.php` içerisindeki yedek değişkene yazın:
     ```php
     $AUTH_KEY = getenv('RELAY_AUTH_TOKEN') ?: 'buraya_cok_guclu_rastgele_bir_token_yazin';
     ```

---

### 2. Adım: Hedef Bilgisayarın Kurulumu (Erişilmek İstenen Makine)

1. Hedef makinede depoyu klonlayın ve klasöre girin:
   ```bash
   git clone https://github.com/djtvyutube/https_ssh_tunnel.git
   cd https_ssh_tunnel
   ```
2. Sanal ortam oluşturun ve bağımlılıkları yükleyin:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Yerel OpenSSH servisinin çalıştığından emin olun:
   ```bash
   sudo systemctl status ssh
   # Eğer çalışmıyorsa: sudo systemctl start ssh
   ```
4. Bağlantıyı doğrulamak için teşhis testini çalıştırın:
   ```bash
   python3 ssh.py --mode test \
     --relay-url "https://alan-adiniz.com/ssh/api.php" \
     --token "buraya_cok_guclu_rastgele_bir_token_yazin"
   ```
5. Sunucu dinleyicisini başlatın:
   ```bash
   python3 ssh.py --mode server \
     --relay-url "https://alan-adiniz.com/ssh/api.php" \
     --token "buraya_cok_guclu_rastgele_bir_token_yazin" \
     --port 22
   ```
   *(Sunucu, relay üzerinden gelecek olan tünel bağlantılarını dinlemeye başlayacaktır).*

#### (İsteğe Bağlı) Hedef Sunucuyu Systemd Servisi Olarak 7/24 Çalıştırma

Terminal kapansa bile tünelin Linux üzerinde sürekli açık kalması için bir systemd servisi oluşturabilirsiniz:

```bash
sudo nano /etc/systemd/system/https-ssh-tunnel.service
```

Aşağıdaki yapılandırmayı yapıştırın (kullanıcı adı ve dosya yollarını kendinize göre güncelleyin):

```ini
[Unit]
Description=HTTP(S) Relay Tunnel for SSH (Target Server)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/https_ssh_tunnel
ExecStart=/home/ubuntu/https_ssh_tunnel/venv/bin/python3 ssh.py --mode server --relay-url "https://alan-adiniz.com/ssh/api.php" --token "buraya_cok_guclu_rastgele_bir_token_yazin" --port 22
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Servisi etkinleştirip başlatın:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now https-ssh-tunnel
```

---

### 3. Adım: İstemci Bilgisayarın Kurulumu (Kendi Yerel Bilgisayarınız)

1. Kendi bilgisayarınızda depoyu klonlayın ve klasöre girin:
   ```bash
   git clone https://github.com/djtvyutube/https_ssh_tunnel.git
   cd https_ssh_tunnel
   ```
2. Sanal ortam oluşturup bağımlılıkları yükleyin:
   * **Linux / macOS:**
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     pip install -r requirements.txt
     ```
   * **Windows (PowerShell):**
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     pip install -r requirements.txt
     ```
3. İstemci köprüsünü başlatın:
   ```bash
   python3 ssh.py --mode client \
     --relay-url "https://alan-adiniz.com/ssh/api.php" \
     --token "buraya_cok_guclu_rastgele_bir_token_yazin" \
     --port 2222
   ```
   *(İstemci, yerel makinenizde `127.0.0.1:2222` portunu dinlemeye alacaktır).*

---

### 4. Adım: SSH / SFTP ile Bağlanma

Yerel bilgisayarınızda yeni bir terminal penceresi açın ve yerel köprü portu üzerinden doğrudan bağlanın:

```bash
# Etkileşimli SSH kabuk bağlantısı
ssh <uzak_kullanici>@127.0.0.1 -p 2222

# SCP ile dosya yükleme
scp -P 2222 ./yerel_dosya.tar.gz <uzak_kullanici>@127.0.0.1:/home/<uzak_kullanici>/

# SCP ile dosya indirme
scp -P 2222 <uzak_kullanici>@127.0.0.1:/var/log/syslog ./syslog_yedek.log
```

---

## Komut Satırı Parametreleri Referansı

| Seçenek | Parametre | Açıklama | Varsayılan |
| :--- | :--- | :--- | :--- |
| **Mod** | `--mode` | Çalışma modu: `client`, `server` veya `test` | `client` |
| **Relay URL** | `--relay-url` | `api.php` dosyasının tam HTTPS adresi | `RELAY_URL` ortam değişkeni |
| **Token** | `--token` | Önceden paylaşılan gizli kimlik doğrulama anahtarı | `RELAY_TOKEN` ortam değişkeni |
| **Port** | `--port` | İstemci için yerel dinleme portu, sunucu için hedef SSH portu | `2222` (client) / `22` (server) |
| **SSH Host** | `--ssh-host` | Hedef makinedeki SSH sunucu IP adresi | `127.0.0.1` |
| **Hata Ayıklama** | `--debug` | Detaylı paket sırası, gecikme ve veri akışı loglarını gösterir | `False` |

---

## Üretim Ortamı İçin Güvenlik Tavsiyeleri

1. **Zorunlu HTTPS (TLS 1.2 / 1.3)**: `api.php` dosyasını her zaman geçerli bir SSL sertifikası altında çalıştırın. Standart TLS şifrelemesi, internet üzerinden aktarılan tüm verilerinizin güvende kalmasını sağlar.
2. **Kriptografik Güçlü Tokenlar**: Kimlik doğrulama anahtarı için `openssl rand -hex 32` komutuyla yüksek entropili rastgele anahtarlar üretin.
3. **SSH Anahtar Doğrulaması**: Hedef makinenin `/etc/ssh/sshd_config` dosyasında parola ile girişi kapatın (`PasswordAuthentication no`) ve SSH anahtarlarıyla (`~/.ssh/authorized_keys`) giriş yapın.
4. **Veri Klasörünü Koruma**: Yetkisiz kişilerin paket kuyruklarına erişmesini önlemek için `.relay_data/` dizinine web üzerinden doğrudan erişimi engelleyin.
5. **IP Filtreleme / WAF Kuralları**: Mümkünse Cloudflare veya sunucu güvenlik duvarı üzerinden `api.php` dosyasına yalnızca kendi IP aralıklarınızın erişmesine izin verin.

---

## Lisans

Bu proje MIT Lisansı ile lisanslanmıştır - ayrıntılar için [LICENSE](LICENSE) dosyasına bakabilirsiniz.
