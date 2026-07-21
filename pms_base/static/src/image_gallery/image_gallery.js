/** @odoo-module **/

import { Component, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ImageGallery extends Component {

    static template = "pms_base.ImageGallery";

    static props = {
        record: Object,
        name: String,
        readonly: {
            type: Boolean,
            optional: true,
        },
    };

    get list() {
        return this.props.record.data[this.props.name];
    }

    get records() {
        console.log(this.list.records);
        return this.list.records;
    }
    setup() {
        this.fileInput = useRef("fileInput");
        this.orm = useService("orm");
        console.log("LIST", this.list);
        console.log("RECORDS", this.records);


        if (this.records.length) {
            const record = this.records[0];

            console.log("FIRST RECORD", record);
            console.log("FIRST RECORD DATA", record.data);
            console.log("FIRST RECORD KEYS", Object.keys(record));
            console.log("FIRST RECORD DATA KEYS", Object.keys(record.data));

            console.log("ID", record.id);
            console.log("RES ID", record.resId);
            console.log("DATA ID", record.data.id);
            console.log("IMAGE", record.data.image);
            const img = this.records[0].data.image;
        }
        
        const proto = Object.getPrototypeOf(this.list);

    }
    openFileDialog() {
        this.fileInput.el.click();
    }
    async onFileSelected(ev) {

        const file = ev.target.files[0];
        if (!file) {
            return;
        }

        const base64 = await this.readFile(file);

        const propertyId = this.props.record.resId;

        await this.orm.create(
            "real.estate.property.image",
            [{
                property_id: propertyId,
                name: file.name,
                image: base64,
            }]
        );

        // recargar el one2many
        console.log("RELOAD ONE2MANY");
        await this.props.record.model.load();

    }
    readFile(file) {

        return new Promise((resolve) => {

            const reader = new FileReader();

            reader.onload = () => {

                resolve(
                    reader.result.split(",")[1]
                );

            };

            reader.readAsDataURL(file);

        });

    }

    async deleteImage(record) {
        await this.orm.unlink(
            "real.estate.property.image",
            [record.resId]
        );

        await this.props.record.model.load();

    }

}