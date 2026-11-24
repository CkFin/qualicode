# Proxy inverso: nginx oficial sin privilegios (uid 101) con el frontend incluido.
FROM nginxinc/nginx-unprivileged:1.27-alpine

USER root
COPY proxy/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/ /usr/share/nginx/html/
RUN chmod -R a+rX,go-w /usr/share/nginx/html /etc/nginx/conf.d
USER 101

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
