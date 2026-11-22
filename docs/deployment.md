# Deploying the live demo

The live demo runs on one free Oracle Cloud server, with the same Docker Compose setup as
local development plus [docker-compose.prod.yml](../docker-compose.prod.yml). Caddy sits in
front and handles HTTPS. Follow the steps in order. They also work as a **rebuild guide**:
if Oracle ever reclaims the server, start again at step 2.

What it costs: nothing. Stay on Oracle's **Free Tier**. Never upgrade the account to
Pay-As-You-Go, because then going over the free limits would cost money.

What the demo does differently from a real garage site (`DEMO_SITE=true`):

- It has the two demo staff logins.
- It never sends email. Each email goes to the public **Demo inbox** page instead.
- It resets everything back to the demo data at 03:00 UK time every night.

Everything else runs with production settings: Stripe (test mode) is required and the rate
limits are on.

Commands marked **(your PC)** run in PowerShell on Windows. All the others run on the server,
over SSH.

---

## 1. Oracle Cloud account

1. Sign up at [cloud.oracle.com](https://www.oracle.com/cloud/free/). It asks for a card to
   check who you are, but a Free Tier account is never charged.
2. Pick a home region close to you, such as UK South (London). You can't change it later,
   and free servers can only be made in the home region.
3. Don't upgrade the account.

## 2. The server

First make the network. The create-instance form can make one too, but then it won't let
you turn on the public IP address. Go to **Networking → Virtual cloud networks → Start VCN
Wizard → Create VCN with Internet Connectivity**, name it `garage-vcn`, and create it.

Then go to **Compute → Instances → Create instance** and set:

- **Name:** `garage-demo`
- **Image:** Canonical Ubuntu 24.04 (not Minimal)
- **Shape:** Ampere, `VM.Standard.A1.Flex`, 2 OCPUs and 12 GB memory. That's inside the free
  allowance: the cost estimate shows no charge for the server itself. Oracle changes the
  allowance from time to time, so check that the shape says **Always Free-eligible**.
- **Networking:** the existing `garage-vcn` and its **public** subnet, with **Automatically
  assign public IPv4 address** turned on
- **SSH keys:** **Save private key**. Keep the file. It's the only way in.
- Leave everything else as it is.

The cost estimate shows a small monthly charge for the boot volume. It ignores the free
allowance, which covers 200 GB of disk, so a Free Tier account isn't charged.

If creation fails with **Out of capacity**, try another availability domain (the dropdown
in the Placement section), or try again later. Free Arm capacity comes and goes.

Note the server's **public IP address** from the instance page.

**(your PC)** Connect. Replace the paths and the IP with yours:

```powershell
icacls C:\path\to\ssh-key.key /inheritance:r /grant:r "$($env:USERNAME):R"
ssh -i C:\path\to\ssh-key.key ubuntu@<public-ip>
```

## 3. Open ports 80 and 443

The server is behind two firewalls, and you need to open both.

**Oracle's firewall.** Go to the instance → **Subnet** → **Default Security List** → **Add
Ingress Rules**, and add three rules, all with source `0.0.0.0/0`:

- TCP, destination port 80
- TCP, destination port 443
- UDP, destination port 443

**The server's own firewall.** Oracle's Ubuntu image blocks everything except SSH:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 4. A free address (DuckDNS)

1. Sign in at [duckdns.org](https://www.duckdns.org) and add a subdomain, for example
   `hillside-garage-demo`.
2. Set its **current ip** to the server's public IP and press **update ip**.
3. **(your PC)** Check it: `nslookup hillside-garage-demo.duckdns.org` should answer with
   the server's IP.

The public IP stays the same while the server exists. If you rebuild the server, update
the IP on DuckDNS.

## 5. Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

Reconnect with the same `ssh` command, then check: `docker compose version`.

## 6. The code and its settings

```bash
git clone https://github.com/Adxm1go7/car-repair.git
cd car-repair
cp .env.production.example .env
openssl rand -hex 32   # a password for the database: copy it
nano .env
```

Use `-hex`, not `-base64`. The password goes inside the database address, where a `/` or
`+` would break it.

If you can't paste into `nano`, fill in a copy of `.env.production.example` on your PC
instead (outside the project folder), upload it with
`scp -i <key> <file> ubuntu@<public-ip>:car-repair/.env`, then delete the copy on your PC.

In `.env`, set:

- `SITE_ADDRESS`: your DuckDNS name;
- `PUBLIC_BASE_URL`: the same name with `https://` in front;
- `POSTGRES_PASSWORD`: the password you just made;
- the two Stripe **test** keys;
- `STRIPE_WEBHOOK_SECRET`: you get this in step 7.

Save with Ctrl+O, Enter, then Ctrl+X.

## 7. Stripe webhook

In the Stripe dashboard, in **test mode**, go to **Developers → Webhooks → Add endpoint**:

- **Endpoint URL:** `https://<your-name>.duckdns.org/api/stripe/webhook`
- **Events:** `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
  `checkout.session.expired`, `refund.created`, `refund.updated`, `charge.refund.updated`

Copy its **Signing secret** (`whsec_...`) into `.env` as `STRIPE_WEBHOOK_SECRET`.

## 8. First start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait --wait-timeout 600
```

The first build takes a few minutes. Caddy gets the HTTPS certificate on the first visit.

## 9. Check it

```bash
curl -sI https://<your-name>.duckdns.org/ | grep -i strict-transport
curl -s https://<your-name>.duckdns.org/api/health
curl -s https://<your-name>.duckdns.org/api/garage
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs worker | grep "worker started"
```

You should see:

- `strict-transport-security: max-age=31536000`;
- `"status":"ok"`;
- `"demo_site":true`;
- a worker line that ends `emails: demo inbox`.

**A visitor can't fake their address.** The rate limits and the login lockout count each
visitor's real address. Test it with one wrong login that claims to come from `1.2.3.4`.

**(your PC)**:

```powershell
$site = 'https://<your-name>.duckdns.org'
try {
  Invoke-WebRequest -Method Post -Uri "$site/api/staff/login" -ContentType 'application/json' `
    -Headers @{ 'X-Forwarded-For' = '1.2.3.4'; Origin = $site } `
    -Body '{"email":"nobody@example.test","password":"wrong"}'
} catch { $_.Exception.Response.StatusCode }
```

It prints `Unauthorized`. Then, on the server:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  psql -U garage -d garage -tAc "select ip from login_attempts order by id desc limit 1"
```

It should print your home internet address, not `1.2.3.4`.

Then, in a browser:

1. Book an MOT and pay with card `4242 4242 4242 4242`, any future date and any CVC.
2. Open the **Demo inbox** from the footer. The confirmation email is there, and its link
   opens the booking.
3. Log in at `/staff` with `admin@example.test` / `demo-admin-pass`.

## Everyday commands

Run these from the `car-repair` folder. `dc` is a short name for the long compose command:

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
```

- **Update to the latest code:** `git pull && dc up -d --build --wait`
- **Reset the demo now:** `dc exec api python -m app.demo_reset`
- **Logs:** `dc logs -f api worker`
- **Stop everything:** `dc down`. This keeps the data. Never add `-v` unless you want to
  delete the database and the certificate.

## Running the end-to-end tests against the live site

Do this at a quiet time. The tests make bookings and change settings, and the reset
afterwards wipes any visitor's booking.

**(your PC)**, in the `e2e` folder:

```powershell
$env:BASE_URL = 'https://<your-name>.duckdns.org'
$env:INBOX = 'demo'
npm test
Remove-Item Env:BASE_URL, Env:INBOX
```

The rate limits are on, and all the tests come from your one address. If a test fails with
"Too many attempts" (a 429), wait 15 minutes and run the remaining spec files on their own,
for example `npx playwright test tests/staff-schedule.spec.ts`. Never loosen the limits for
this.

Afterwards, reset the demo on the server: `dc exec api python -m app.demo_reset`.

## If Oracle reclaims the server

Oracle can reclaim a Free Tier server that sits idle for a week. Start again at step 2. In
step 4, update the IP on DuckDNS, and in step 7, Stripe's endpoint stays the same, so reuse
its signing secret. All the demo's data comes from the seed, so nothing is lost.
