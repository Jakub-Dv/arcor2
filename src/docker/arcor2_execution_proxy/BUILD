shell_source(name="start.sh", source="start.sh")

docker_image(
    name="arcor2_execution_proxy",
    repository="arcor2/arcor2_execution_proxy",
    dependencies=[":start.sh"],
    image_tags=["1.0.0"],
)
