# Deploying OptiStock on the AWS free tier

Everything in this file is the part **only you can do** — it needs a card, an
inbox, or a decision. Configured to cost **nothing for twelve months**.

Work through it in order. Each stage produces something the next one needs.
Nothing is urgent; stop whenever you like and pick it up later.

---

## Your settings, already in the code

| Setting | Value | Why |
|---|---|---|
| Region | `ap-south-1` (Mumbai) | Your users and seed data are in India |
| Instance | `t2.micro` | What the free tier covers in Mumbai |
| Disk | 20 GB gp2 | Inside the 30 GB free allowance |
| Swap | 4 GB | So the build survives on 1 GB of RAM |
| Budget alarm | Built by Terraform | Emails you at the first cent |

**Everything must happen in the Mumbai region.** Key pairs, instances and
security groups are region-scoped. A key pair made in Stockholm is invisible
from Mumbai and the deploy fails with a confusing "key not found".

Switch it in the AWS console: top right, where the region name is.

---

## What it costs

**$0 per month for twelve months.** One `t2.micro` running all month is 730
hours of the 750-hour allowance. The disk and the public IP are covered too.

Three things end that:

1. **The free tier lasts 12 months from signup.** Then roughly $8-10/month.
   Put a calendar reminder at **eleven months** — this is the most predictable
   surprise here.
2. **A second server** burns the 750 hours twice as fast. Never run
   `terraform apply` from two different folders.
3. **AWS moved to a credit-based free plan for new accounts in 2025.** Read the
   current terms on the AWS free tier page rather than trusting these numbers.

The only real cost anywhere is a domain (~$12/year), and only if you want
HTTPS at stage 10. Certificates themselves are free.

---

## Stage 1 — Create an AWS account — DONE

You already have one (account `220438080921`).

If you have not already: turn on MFA for your root login. Search **IAM** →
**Add MFA** on the root user. An AWS account without it is the most common way
beginners lose control of their account.

---

## Stage 2 — Create a login for the tools (~10 min)

Your main AWS login is for you, in a browser. The tools on your laptop need
their own, so that if it ever leaks you delete just that one.

1. Console → search **IAM** → **Users** → **Create user**
2. Name it `terraform`
3. Permissions → **Attach policies directly** → tick **AdministratorAccess**
   (broader than ideal; narrowing it properly is a project of its own)
4. Open the new user → **Security credentials** → **Create access key** →
   choose **Command Line Interface (CLI)**
5. You get two strings. **The secret one is shown once and never again.**

Then install the AWS CLI and hand it those strings:

```powershell
# Install, then restart your terminal
winget install -e --id Amazon.AWSCLI

# Paste the two keys when asked.
# Region: ap-south-1     Output format: json
aws configure

# Check it worked
aws sts get-caller-identity
```

**You should see** a small block of JSON with your account number and
`.../terraform` at the end of the `Arn` line.

> **Never** paste these keys into a file inside the project, a chat, or a
> screenshot. `aws configure` deliberately stores them outside the project.

---

## Stage 3 — Confirm the free instance type (~2 min)

The budget alarm used to live here; Terraform builds it now. What is left is
the one free-tier fact that varies by region.

Open <https://aws.amazon.com/free/>, find the EC2 entry, and check it names
`t2.micro` for Mumbai. That is what your config is set to.

If it says `t3.micro` instead, tell me and I will change one line.

> **The catch that gets people:** 750 hours is a month of *one* server (a month
> is about 730 hours). Two servers at once burn it in a fortnight.

---

## Stage 4 — Create the server key (~5 min, downloads once)

This file is the password to your server. AWS generates it, gives it to you
once, and keeps no copy.

**Make sure the console is in Mumbai first.**

Console → **EC2** → **Key Pairs** (left sidebar, under Network & Security) →
**Create key pair**.

- Name: `optistock-prod-key` — spelled **exactly** like that. Terraform already
  refers to this name; a typo means stage 6 fails.
- Type: **RSA**, Format: **.pem**

It downloads immediately. Move it somewhere safe that is **not inside the
project folder** — for example `C:\Users\katre\keys\`. Then lock it down,
because SSH refuses a key that anyone can read:

```powershell
icacls "optistock-prod-key.pem" /inheritance:r
icacls "optistock-prod-key.pem" /grant:r "$env:USERNAME:(R)"
```

> **If you lose this file** there is no recovery and no reset. You would delete
> the server and rebuild from stage 6. Back it up somewhere private now.

---

## Stage 5 — Find your own IP (~2 min)

The server refuses SSH from everywhere except the address you name. The config
rejects an attempt to open it to the whole internet.

```powershell
curl ifconfig.me
```

That prints something like `203.0.113.4`. The value you need next is that with
`/32` on the end: `203.0.113.4/32`.

> Home IP addresses change. If SSH stops working later, this is almost always
> why — re-run this and update the rule under EC2 → Security Groups.

---

## Stage 6 — Build the server (~20 min, still $0)

Terraform reads `terraform/` and creates the matching things in AWS: a network,
a firewall, a server, a fixed address, and the budget alarm. You click nothing.

```powershell
# Install Terraform, then restart your terminal
winget install -e --id Hashicorp.Terraform

cd C:\Users\katre\Desktop\project_IV\terraform

# Downloads the AWS plugin. Once only.
terraform init

# Shows what it WILL do. Changes nothing. Read it.
terraform plan -var="ssh_allowed_cidr=203.0.113.4/32" -var="alert_email=you@example.com"

# Actually builds it. Type: yes
terraform apply -var="ssh_allowed_cidr=203.0.113.4/32" -var="alert_email=you@example.com"
```

Replace the IP with yours from stage 5, and the email with an inbox you
actually read — that is where the spend alarm goes.

**You should see** `Apply complete!` and an output containing a public IP
address. **That address is `EC2_HOST` in stage 8.** Copy it somewhere.

> **A file appears that you must keep.** `terraform.tfstate` is Terraform's
> record of what it built. Delete it and Terraform forgets the server exists
> and will happily build a second one you also pay for. It is already
> git-ignored — just do not delete it, and back it up.

---

## Stage 7 — Put the code on the server (~10 min)

The server installs Docker and creates an empty project folder on first boot.
The one thing it cannot do is fetch your code — it does not know your
repository address. That part is manual, once.

Wait about three minutes after stage 6, then:

```powershell
ssh -i "C:\Users\katre\keys\optistock-prod-key.pem" ubuntu@SERVER_IP
```

Type `yes` when it asks whether you trust the host. Then, on the server:

```bash
# Confirm the automatic setup finished
docker --version

# Fetch your code into the folder that already exists
cd /home/ubuntu/project_IV
git clone https://github.com/zencodermohit/optistock.git .

exit
```

> **If Docker is "not found"** the setup has not finished. Wait two minutes.
> **If the clone asks for a password** your repo is private — tell me and I
> will walk you through a deploy key.

---

## Stage 8 — Give GitHub the six secrets (~15 min)

The deploy writes production secrets onto the server each run, reading them
from GitHub — the only place they are stored.

Generate the two random ones first. **Run this twice and keep the outputs
different:**

```powershell
cd C:\Users\katre\Desktop\project_IV
.\venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

GitHub → your repo → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**. Add these six:

| Name | What to put in it |
|---|---|
| `EC2_HOST` | The IP from stage 6. Digits and dots only, no `http://` |
| `EC2_SSH_KEY` | The **entire** `.pem` file. Open in Notepad, copy everything including the BEGIN and END lines |
| `DB_PASSWORD` | First random string |
| `PROD_SECRET_KEY` | Second random string. Signs everyone's login session |
| `PUBLIC_ORIGIN` | `http://SERVER_IP` — this one **does** need `http://`, and no trailing slash |
| `GEMINI_API_KEY` | Optional, free from aistudio.google.com. Leave empty and the Assistant screen just says it is not configured |

> **The most common mistake:** pasting only part of the `.pem`. It must include
> the first and last lines and the line breaks, or you get a confusing
> "handshake failed" during the deploy.

---

## Stage 9 — Deploy (~40 min, goes live)

Pushing to `main` triggers the deployment. There is no separate button.

**Do this stage with me, not alone** — the first run is the one most likely to
surface something.

Current state: your work is on a branch called `pre-deployment-hardening`, and
`main` is untouched. Merging it is what starts a deploy.

```powershell
cd C:\Users\katre\Desktop\project_IV
git checkout main
git merge pre-deployment-hardening
git push origin main
```

Then GitHub → **Actions** tab and watch the run.

**Expect 20-40 minutes.** That is the price of the free tier, not a fault. A
`t2.micro` has one CPU and 1 GB of memory, and the build compiles the React
bundle and installs pandas, numpy and pyarrow, partly in swap. Running the app
afterwards is unaffected — the whole stack sits at 347 MB. Leave it alone.

When it goes green:

```powershell
curl http://SERVER_IP/health
```

You want `{"status":"ok", ...}` back. Then open `http://SERVER_IP` in a browser
and sign in.

> **If the run goes red**, click into it and read the failing step. Nothing is
> broken on the server — the build now runs before anything is stopped, so a
> failure leaves the previous version untouched. Send me the error.

---

## Stage 10 — A domain, so logins stop travelling in the clear

Until this is done, every password typed into your login page crosses the
internet as readable text. This is the main reason not to let real people use
it yet.

Certificates cannot be issued for a bare IP. You need a name — **the only thing
in this document that is not free**, about $12/year.

1. Buy a domain from any registrar (Namecheap, Cloudflare, GoDaddy)
2. In its DNS settings add an **A record** pointing at your server IP
3. Wait — ten minutes to a few hours
4. Check with `ping yourdomain.com`; when it answers with your IP, it is ready

**Then tell me.** I will write the HTTPS config and certificate renewal and
walk you through the one command that runs on the server. You will also update
`PUBLIC_ORIGIN` to `https://yourdomain.com` and deploy once more.

---

## Five things to never do

1. Never commit `.env`, a `.pem` file, or your AWS keys. Git is set to refuse
   all three — do not work around it.
2. Never set the SSH rule to `0.0.0.0/0`. The config rejects it; that rejection
   is a feature.
3. Never delete `terraform.tfstate`.
4. Never run `terraform apply` from two folders — two servers burn the free
   allowance in a fortnight.
5. Never ignore an email from AWS Budgets. It only fires when real money is
   being spent.

---

## After stage 9

You will have a working, publicly reachable application costing nothing —
enough to demonstrate, to put on a CV, to show someone.

What you will **not** have is somewhere safe for real inventory data: no
backups yet, no encryption in transit until stage 10, and one server with no
spare. Backups and the undo-a-bad-deploy path are being built separately, so
those close without work from you.

And set that eleven-month calendar reminder today, while you are thinking
about it.
