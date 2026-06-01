# Setting Up a WordPress Application Password

`wp-index` can read a WordPress site without any password (published content is public). You only need an Application Password if you want to include drafts and private items, or to resolve author display names reliably. If you only need published content, skip this guide and run without credentials.

## What an Application Password is

Application Passwords allow authentication for non-interactive systems, such as the REST API or XML-RPC, without exposing your real login password. Each one is a separate credential, scoped to a single named integration, and can be revoked at any time. They cannot be used to log in to the WordPress dashboard, so a leaked Application Password cannot take over the account the way a stolen real password could.

## Before you start

1. WordPress 5.6 or newer. Application Passwords have been a core feature since December 2020.

2. The site must be served over HTTPS. On a plain `http://` site WordPress hides the feature completely. The only exception is a local development host (for example `localhost`), which is allowed without HTTPS.

3. A user account that can create Application Passwords. Every user can create their own; an Administrator can manage them for others. For `wp-index`, prefer a least-privilege account (see the section below).

4. The web server must pass the `Authorization` header through to PHP. Most do. Some Apache or CGI setups strip it, which breaks authentication even when the password is correct (fix below).

## The normal path (when nothing is blocking it)

1. Log in to the WordPress admin.

2. Go to Users, then Profile (or Users, then your user, then Edit).

3. Scroll to the "Application Passwords" section near the bottom of the profile.

4. Type a name you will recognise later, for example "wp-index extractor".

5. Click "Add New Application Password".

6. Copy the generated password immediately. It is shown once and never again. The spaces in it are only for readability; you can keep them or remove them.

7. Authenticate with your normal WordPress username (not the application name you just typed) as `WP_USER`, and the generated value as `WP_APP_PASSWORD`.

## When the Application Passwords section is missing

This is the common real-world case. If the section is not on the profile page at all, something is hiding it. Work down this list in order, since HTTPS and security plugins are by far the most frequent causes.

### 1. The site is not on HTTPS

The single most common cause. If the site loads over `http://`, WordPress removes the feature with no message. Install an SSL certificate and force all traffic to `https://`, then reload the profile page. (Local development hosts are exempt and can use Application Passwords without HTTPS.)

### 2. Patchstack is blocking it

Patchstack ships a hardening rule called "Block WordPress application passwords" that is enabled by default. This is the one that bit the iDD academy on its first setup.

1. Dashboard route. Open the Patchstack App, select the site, go to Hardening, then General, and turn off "Block application passwords".

2. WP-CLI route. Run `wp option update patchstack_application_passwords_disabled 0` on the server. This is the exact command that restored the option for the iDD academy.

### 3. Wordfence is blocking it

Wordfence has a brute-force setting that disables the feature.

1. Go to Wordfence, then All Options.

2. If the sections look collapsed, click "EXPAND ALL" near the top right.

3. Find the "Brute Force Protection" section and locate "Disable WordPress application passwords".

4. Uncheck it (set it to off), click "Save Changes", and clear any cache.

### 4. Solid Security (formerly iThemes Security) is blocking it

Solid Security can restrict the REST API and Application Passwords from its tweaks settings.

1. Open Solid Security settings.

2. Find the "WordPress Tweaks" area (older versions) or the REST API and Application Passwords controls.

3. Allow Application Passwords. The Pro version adds finer control, such as limiting a password to REST API use only, which is a good fit for `wp-index`.

### 5. A theme or a snippet disables it

The feature is gated by the core filter `wp_is_application_passwords_available` (and a per-user variant). Any snippet that returns false will hide it. Search the active theme's `functions.php` and any "code snippets" plugin for that filter name and remove or correct the snippet.

### 6. Multisite

On a multisite network, Application Passwords can be switched off network-wide. A network administrator may need to enable them before any single site shows the option.

### 7. The server strips the Authorization header

If the section appears and you can create a password, but authentication still fails with a 401, the server is probably dropping the `Authorization` header before PHP sees it. On Apache, add this to `.htaccess`:

```
SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1
```

Newer Apache also supports `CGIPassAuth On`. On Nginx with PHP-FPM the header usually passes through already.

## Verifying it works

Before running `wp-index`, confirm the credential with a single request against the REST API:

```
curl --user "USERNAME:APP PASSWORD" https://your-site.com/wp-json/wp/v2/users/me
```

A 200 response with your user details as JSON means the password works. A 401 means either the credential is wrong or the `Authorization` header is being stripped (see step 7 above).

## Using least privilege

An Application Password inherits the full capabilities of the user it belongs to. Because `wp-index` only reads (it never writes to your site), you do not need an Administrator. Where possible, create or use an Editor-level account, give the password a clear name, and revoke it when the extraction work is done. This keeps the blast radius small if the credential is ever exposed.

## Revoking

Go to Users, then Profile, then the "Application Passwords" section, and click "Revoke" next to the entry (or "Revoke all application passwords"). Revocation takes effect immediately and has no effect on your normal dashboard login.

## Sources

- [Application Passwords - WordPress Advanced Administration Handbook](https://developer.wordpress.org/advanced-administration/security/application-passwords/)

- [General hardening - Patchstack Docs](https://docs.patchstack.com/patchstack-app/site-dashboard/hardening/app-hardening-general/)

- [WP options - Patchstack Docs](https://docs.patchstack.com/patchstack-plugin/wp-options/)

- [Application Passwords disabled by Wordfence - WordPress.org support](https://wordpress.org/support/topic/wordpress-application-passwords-disabled-by-wordfence-plugin/)

- [Solid Security settings - SolidWP documentation](https://solidwp.com/documentation/security/how-it-works/security-settings/)
