# Email OTP — Yahoo, Outlook et Hotmail

## Cause traitée

L'application envoie les OTP transactionnels via l'API HTTPS Brevo. L'acceptation
par Brevo ne garantit pas à elle seule la livraison en boîte de réception : les
fournisseurs destinataires vérifient l'authentification et la réputation du domaine
expéditeur.

## Configuration Render

Définir au minimum :

- `OTP_DELIVERY_MODE=email`
- `EMAIL_PROVIDER=brevo`
- `BREVO_API_KEY`
- `BREVO_FROM_EMAIL`
- `BREVO_FROM_NAME` (facultatif)

`BREVO_FROM_EMAIL` doit utiliser votre propre domaine, par exemple
`no-reply@wfm.example.com`. Ne pas utiliser `@gmail.com`, `@yahoo.com`,
`@outlook.com` ou `@hotmail.com` comme expéditeur de production.

`BREVO_REPLY_TO_EMAIL` est facultatif.

## Configuration Brevo / DNS

Dans Brevo, ajouter et authentifier le domaine expéditeur. Publier les enregistrements
demandés par Brevo pour le code de domaine, DKIM et DMARC. Vérifier ensuite que le
domaine apparaît comme **Authenticated**.

Pour les tests, envoyer d'abord vers une adresse de contrôle sur Gmail, Yahoo et
Outlook/Hotmail. Dans Brevo, vérifier ensuite les événements **Delivered**, **Blocked**,
**Hard Bounce**, **Soft Bounce** et **Deferred**.

## Diagnostic applicatif

Après un envoi OTP, les logs Render contiennent maintenant l'identifiant `messageId`
retourné par Brevo lorsque la requête est acceptée. Cet identifiant permet de suivre
l'événement transactionnel dans Brevo.

L'application refuse désormais en production les expéditeurs utilisant des domaines
de messagerie gratuits, avec un message explicite au lieu de tenter un envoi avec une
identité peu fiable.
